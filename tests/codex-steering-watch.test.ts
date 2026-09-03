import { expect, test } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  CodexSteeringLogWatcher,
  codexUserRevisionText,
  consumeInjectedCodexSteerReplay,
  decodeRustDebugString,
  markInjectedCodexSteersSettled,
  parseCodexSteerSubmission,
  recordInjectedCodexSteer,
  resetInjectedCodexSteerReplayRegistryForTests,
} from "../src/adapters/chatgpt-web/codex-steering-watch";

const target = "codex_core::session::handlers";
const threadId = "01thread";
const turnId = "01turn";

function submissionRow(id: number, text: string, mode = `Steer { expected_turn_id: \\"${turnId}\\" }`) {
  const encoded = JSON.stringify(text).slice(1, -1);
  return {
    id,
    target,
    thread_id: threadId,
    message: `Submission { id: \\"sub\\", op: TurnInput { request: TurnInputRequest { input: UserInput([Text { text: \\"${encoded}\\", text_elements: [] }]) }, mode: ${mode}, reply: Sender { .. } } }`,
  };
}

test("Rust debug strings decode the escapes used by Codex TurnInput", () => {
  expect(decodeRustDebugString('line 1\\nquote: \\"x\\"\\t\\u{1f642}')).toBe('line 1\nquote: "x"\t🙂');
});

test("only an exact native Steer TurnInput becomes an immediate relay submission", () => {
  const parsed = parseCodexSteerSubmission(submissionRow(12, 'steer now\nwith "quotes"'));
  expect(parsed).toEqual({
    logId: 12,
    threadId,
    turnId,
    text: 'steer now\nwith "quotes"',
  });
  expect(parseCodexSteerSubmission(submissionRow(13, "ordinary", "StartOrSteer"))).toBeUndefined();
  expect(parseCodexSteerSubmission({ ...submissionRow(14, "wrong target"), target: "other" })).toBeUndefined();
});

test("canonical Responses user revisions use the same text representation as steer logs", () => {
  expect(codexUserRevisionText([
    { type: "input_text", text: "first" },
    { type: "input_text", text: "second" },
  ])).toBe("first\nsecond");
  expect(codexUserRevisionText([{ type: "input_image", image_url: "data:image/png;base64,AA==" }])).toBeUndefined();
});

test("a mirrored steer is suppressed only after its browser turn physically settles", () => {
  resetInjectedCodexSteerReplayRegistryForTests();
  const steer = { logId: 20, threadId, turnId, text: "new direction" };
  recordInjectedCodexSteer(steer);
  expect(consumeInjectedCodexSteerReplay(threadId, turnId, steer.text)).toBeFalse();
  markInjectedCodexSteersSettled(threadId, turnId);
  expect(consumeInjectedCodexSteerReplay(threadId, turnId, steer.text)).toBeTrue();
  expect(consumeInjectedCodexSteerReplay(threadId, turnId, steer.text)).toBeFalse();
});

test("the log watcher delivers each new exact steer once to its exact active thread and turn", async () => {
  const directory = mkdtempSync(join(tmpdir(), "codex-steer-watch-"));
  const path = join(directory, "logs_2.sqlite");
  const database = new Database(path, { create: true });
  database.exec(`
    CREATE TABLE logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      ts_nanos INTEGER NOT NULL DEFAULT 0,
      level TEXT,
      target TEXT,
      feedback_log_body TEXT,
      thread_id TEXT
    );
  `);
  database.query(
    "INSERT INTO logs (ts, target, feedback_log_body, thread_id) VALUES (?, ?, ?, ?)",
  ).run(Math.floor(Date.now() / 1000), target, "historical", threadId);

  const watcher = new CodexSteeringLogWatcher(path, 5);
  const received: Array<{ logId: number; text: string }> = [];
  const unsubscribe = watcher.subscribe({
    threadId,
    turnId,
    onSteer: steer => { received.push({ logId: steer.logId, text: steer.text }); },
  });
  await watcher.poll();
  expect(received).toEqual([]);

  const row = submissionRow(2, "live steer");
  database.query(
    "INSERT INTO logs (id, ts, target, feedback_log_body, thread_id) VALUES (?, ?, ?, ?, ?)",
  ).run(row.id, Math.floor(Date.now() / 1000), row.target, row.message, row.thread_id);
  await watcher.poll();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(received).toEqual([{ logId: 2, text: "live steer" }]);
  await watcher.poll();
  expect(received).toHaveLength(1);

  unsubscribe();
  watcher.close();
  database.close();
  rmSync(directory, { recursive: true, force: true });
});
