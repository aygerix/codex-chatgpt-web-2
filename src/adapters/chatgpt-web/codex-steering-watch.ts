import { Database } from "bun:sqlite";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

const CODEX_SUBMISSION_LOG_TARGET = "codex_core::session::handlers";
const DEFAULT_POLL_MS = 125;
const MAX_LOG_ROWS_PER_POLL = 256;
const INJECTED_STEER_TTL_MS = 30 * 60_000;

export interface CodexSteerSubmission {
  logId: number;
  threadId: string;
  turnId: string;
  text: string;
}

interface CodexLogRow {
  id: number;
  target: string | null;
  message: string | null;
  thread_id: string | null;
}

interface SteeringSubscription {
  threadId: string;
  turnId: string;
  onSteer: (submission: CodexSteerSubmission) => void | Promise<void>;
  tail: Promise<void>;
}

interface InjectedSteerRecord extends CodexSteerSubmission {
  injectedAt: number;
  settled: boolean;
}

function defaultCodexLogDatabasePath(): string {
  const configured = process.env.CODEX_HOME?.trim();
  return join(resolve(configured || join(homedir(), ".codex")), "logs_2.sqlite");
}

/** Decode one Rust `Debug` string literal without evaluating arbitrary source. */
export function decodeRustDebugString(encoded: string): string {
  let output = "";
  for (let index = 0; index < encoded.length; index += 1) {
    const unit = encoded[index]!;
    if (unit !== "\\") {
      output += unit;
      continue;
    }
    index += 1;
    if (index >= encoded.length) throw new Error("unterminated Rust string escape");
    const escaped = encoded[index]!;
    switch (escaped) {
      case "\\": output += "\\"; break;
      case '"': output += '"'; break;
      case "n": output += "\n"; break;
      case "r": output += "\r"; break;
      case "t": output += "\t"; break;
      case "0": output += "\0"; break;
      case "x": {
        const hex = encoded.slice(index + 1, index + 3);
        if (!/^[0-9a-fA-F]{2}$/.test(hex)) throw new Error("invalid Rust hex escape");
        output += String.fromCodePoint(Number.parseInt(hex, 16));
        index += 2;
        break;
      }
      case "u": {
        if (encoded[index + 1] !== "{") throw new Error("invalid Rust unicode escape");
        const close = encoded.indexOf("}", index + 2);
        if (close < 0) throw new Error("unterminated Rust unicode escape");
        const hex = encoded.slice(index + 2, close);
        if (!/^[0-9a-fA-F]{1,6}$/.test(hex)) throw new Error("invalid Rust unicode code point");
        const codePoint = Number.parseInt(hex, 16);
        if (codePoint > 0x10ffff) throw new Error("Rust unicode code point is out of range");
        output += String.fromCodePoint(codePoint);
        index = close;
        break;
      }
      default:
        throw new Error(`unsupported Rust string escape: \\${escaped}`);
    }
  }
  return output;
}

function rustQuotedCaptures(source: string, prefix: RegExp): string[] {
  const start = prefix.exec(source);
  if (!start || start.index === undefined) return [];
  const scoped = source.slice(start.index);
  const values: string[] = [];
  const pattern = /Text\s*\{\s*text:\s*"((?:\\.|[^"\\])*)"/gs;
  for (const match of scoped.matchAll(pattern)) values.push(match[1]!);
  return values;
}

/** Parse only the exact Codex `TurnInput` debug shape emitted for a native Steer submission. */
export function parseCodexSteerSubmission(row: CodexLogRow): CodexSteerSubmission | undefined {
  if (!Number.isSafeInteger(row.id) || row.id < 1) return undefined;
  if (row.target !== CODEX_SUBMISSION_LOG_TARGET) return undefined;
  if (typeof row.thread_id !== "string" || !row.thread_id) return undefined;
  if (typeof row.message !== "string" || !row.message.includes("Submission") || !row.message.includes("TurnInput")) {
    return undefined;
  }
  const mode = /mode:\s*Steer\s*\{\s*expected_turn_id:\s*"((?:\\.|[^"\\])*)"\s*\}/s.exec(row.message);
  if (!mode) return undefined;
  let turnId: string;
  try {
    turnId = decodeRustDebugString(mode[1]!);
  } catch {
    return undefined;
  }
  if (!turnId) return undefined;

  const encodedTexts = rustQuotedCaptures(row.message, /op:\s*TurnInput\s*\{/s);
  if (encodedTexts.length === 0) return undefined;
  let text: string;
  try {
    text = encodedTexts.map(decodeRustDebugString).join("\n");
  } catch {
    return undefined;
  }
  if (!text.trim()) return undefined;
  return { logId: row.id, threadId: row.thread_id, turnId, text };
}

/** Canonical visible text for the latest raw Codex user revision carried in a Responses request. */
export function codexUserRevisionText(content: unknown): string | undefined {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return undefined;
  const texts: string[] = [];
  for (const part of content) {
    if (!part || typeof part !== "object" || Array.isArray(part)) return undefined;
    const record = part as Record<string, unknown>;
    if (typeof record.text === "string") {
      texts.push(record.text);
      continue;
    }
    // Immediate steering currently transports text only. Do not claim an image/file steer was
    // mirrored unless the later canonical Codex round can reconstruct it itself.
    return undefined;
  }
  return texts.length > 0 ? texts.join("\n") : undefined;
}

class InjectedSteerReplayRegistry {
  private readonly records: InjectedSteerRecord[] = [];

  record(submission: CodexSteerSubmission, now = Date.now()): void {
    this.prune(now);
    if (this.records.some(record => record.logId === submission.logId)) return;
    this.records.push({ ...submission, injectedAt: now, settled: false });
  }

  settleTurn(threadId: string, turnId: string, now = Date.now()): void {
    this.prune(now);
    for (const record of this.records) {
      if (record.threadId === threadId && record.turnId === turnId) record.settled = true;
    }
  }

  consumeSettledThrough(threadId: string, turnId: string, text: string, now = Date.now()): boolean {
    this.prune(now);
    let matchIndex = -1;
    for (let index = 0; index < this.records.length; index += 1) {
      const record = this.records[index]!;
      if (record.threadId === threadId
        && record.turnId === turnId
        && record.settled
        && record.text === text) matchIndex = index;
    }
    if (matchIndex < 0) return false;
    const matched = this.records[matchIndex]!;
    // Codex drains all queued steer inputs at one provider boundary. When the latest canonical
    // user revision matches a steer already mirrored into the Web turn, retire every older settled
    // steer from the same native turn as part of that same drain.
    for (let index = this.records.length - 1; index >= 0; index -= 1) {
      const record = this.records[index]!;
      if (record.threadId === threadId
        && record.turnId === turnId
        && record.settled
        && record.logId <= matched.logId) this.records.splice(index, 1);
    }
    return true;
  }

  reset(): void {
    this.records.length = 0;
  }

  private prune(now: number): void {
    for (let index = this.records.length - 1; index >= 0; index -= 1) {
      if (now - this.records[index]!.injectedAt > INJECTED_STEER_TTL_MS) this.records.splice(index, 1);
    }
  }
}

const injectedSteerReplayRegistry = new InjectedSteerReplayRegistry();

export function recordInjectedCodexSteer(submission: CodexSteerSubmission): void {
  injectedSteerReplayRegistry.record(submission);
}

export function markInjectedCodexSteersSettled(threadId: string, turnId: string): void {
  injectedSteerReplayRegistry.settleTurn(threadId, turnId);
}

export function consumeInjectedCodexSteerReplay(threadId: string, turnId: string, text: string): boolean {
  return injectedSteerReplayRegistry.consumeSettledThrough(threadId, turnId, text);
}

export function resetInjectedCodexSteerReplayRegistryForTests(): void {
  injectedSteerReplayRegistry.reset();
}

export class CodexSteeringLogWatcher {
  private database?: Database;
  private cursor?: number;
  private timer?: ReturnType<typeof setInterval>;
  private polling = false;
  private readonly subscriptions = new Set<SteeringSubscription>();
  private readonly subscribedAtSeconds = Math.floor(Date.now() / 1000);

  constructor(
    private readonly databasePath = defaultCodexLogDatabasePath(),
    private readonly pollMs = DEFAULT_POLL_MS,
  ) {}

  subscribe(input: {
    threadId: string;
    turnId: string;
    onSteer: (submission: CodexSteerSubmission) => void | Promise<void>;
  }): () => void {
    if (!input.threadId || !input.turnId) throw new Error("Codex steering subscription requires thread and turn ids");
    const subscription: SteeringSubscription = {
      ...input,
      tail: Promise.resolve(),
    };
    this.subscriptions.add(subscription);
    this.ensureTimer();
    void this.poll();
    return () => {
      this.subscriptions.delete(subscription);
      if (this.subscriptions.size === 0) this.stopTimer();
    };
  }

  close(): void {
    this.subscriptions.clear();
    this.stopTimer();
    this.database?.close();
    this.database = undefined;
    this.cursor = undefined;
  }

  async poll(): Promise<void> {
    if (this.polling || this.subscriptions.size === 0) return;
    this.polling = true;
    try {
      if (!this.ensureDatabase()) return;
      const rows = this.database!.query(`
        SELECT id, target, feedback_log_body AS message, thread_id
        FROM logs
        WHERE id > ?
          AND target = ?
        ORDER BY id ASC
        LIMIT ${MAX_LOG_ROWS_PER_POLL}
      `).all(this.cursor ?? 0, CODEX_SUBMISSION_LOG_TARGET) as CodexLogRow[];
      for (const row of rows) {
        this.cursor = Math.max(this.cursor ?? 0, row.id);
        const submission = parseCodexSteerSubmission(row);
        if (!submission) continue;
        for (const subscription of this.subscriptions) {
          if (subscription.threadId !== submission.threadId || subscription.turnId !== submission.turnId) continue;
          subscription.tail = subscription.tail
            .then(() => subscription.onSteer(submission))
            .catch(error => {
              console.error(
                `[chatgpt-web] immediate Codex steer relay failed (logId=${submission.logId}, textChars=${submission.text.length}):`
                + ` ${error instanceof Error ? error.message : String(error)}`,
              );
            });
        }
      }
    } finally {
      this.polling = false;
    }
  }

  private ensureDatabase(): boolean {
    if (this.database) return true;
    if (!existsSync(this.databasePath)) return false;
    try {
      this.database = new Database(this.databasePath, { readonly: true, create: false });
      if (this.cursor === undefined) {
        const current = this.database.query("SELECT COALESCE(MAX(id), 0) AS max_id FROM logs").get() as { max_id?: number } | null;
        // A normal production subscription starts after the log DB already exists: ignore history.
        // If the DB appeared after subscription, retain rows from this subscription's start second
        // so the first steer that created/opened it cannot be skipped.
        const existedBeforeSubscribe = (current?.max_id ?? 0) > 0;
        if (existedBeforeSubscribe) {
          this.cursor = current?.max_id ?? 0;
        } else {
          const prior = this.database.query(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM logs WHERE ts < ?",
          ).get(this.subscribedAtSeconds) as { max_id?: number } | null;
          this.cursor = prior?.max_id ?? 0;
        }
      }
      return true;
    } catch (error) {
      this.database?.close();
      this.database = undefined;
      console.warn(
        `[chatgpt-web] Codex steering log watcher could not open logs_2.sqlite:`
        + ` ${error instanceof Error ? error.message : String(error)}`,
      );
      return false;
    }
  }

  private ensureTimer(): void {
    if (this.timer) return;
    this.timer = setInterval(() => { void this.poll(); }, this.pollMs);
    this.timer.unref?.();
  }

  private stopTimer(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }
}

export const codexSteeringLogWatcher = new CodexSteeringLogWatcher();
