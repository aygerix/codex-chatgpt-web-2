import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  bulletListMarker: "-",
  codeBlockStyle: "fenced",
  fence: "```",
  emDelimiter: "*",
  strongDelimiter: "**",
  linkStyle: "inlined",
});

turndown.use(gfm);
turndown.remove(["button", "script", "style"]);
turndown.addRule("removeImages", {
  filter: node => ["IMG", "PICTURE", "SOURCE"].includes(node.nodeName),
  replacement: () => "",
});
turndown.addRule("removeSvg", {
  filter: node => node.nodeName === "SVG",
  replacement: () => "",
});
turndown.addRule("linkInlineFilePaths", {
  filter: node => inlineFilePath(node) !== undefined,
  replacement: (_content, node) => {
    const path = node.textContent!;
    const target = path.replaceAll("\\", "/");
    return `[${path}](<${target}>)`;
  },
});
turndown.addRule("compactListItem", {
  filter: "li",
  replacement: (content, node, options) => {
    const parent = node.parentNode as HTMLElement | null;
    let prefix = `${options.bulletListMarker} `;
    if (parent?.nodeName === "OL") {
      const start = Number(parent.getAttribute("start") ?? "1");
      const index = Array.prototype.indexOf.call(parent.children, node) as number;
      prefix = `${start + index}. `;
    }
    const normalized = content
      .replace(/^\n+|\n+$/g, "")
      .replace(/\n/g, `\n${" ".repeat(prefix.length)}`);
    return `${prefix}${normalized}${node.nextSibling ? "\n" : ""}`;
  },
});

function inlineFilePath(node: Node): string | undefined {
  if (node.nodeName !== "CODE") return undefined;
  for (let ancestor = node.parentNode; ancestor; ancestor = ancestor.parentNode) {
    if (["A", "PRE"].includes(ancestor.nodeName)) return undefined;
  }

  const path = node.textContent ?? "";
  if (path !== path.trim() || /[\s`<>()[\]]/.test(path)) return undefined;
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(path)) return undefined;

  const withoutLocation = path.replace(/:\d+(?::\d+)?$/, "");
  const separator = Math.max(withoutLocation.lastIndexOf("/"), withoutLocation.lastIndexOf("\\"));
  if (separator < 0) return undefined;

  const basename = withoutLocation.slice(separator + 1);
  if (!/\.[a-z\d][a-z\d._-]*$/i.test(basename)) return undefined;
  return path;
}

function preserveObsidianWikiLinks(markdown: string): string {
  // Turndown escapes literal brackets, but Codex interprets the resulting `\[` as LaTeX.
  // Double-bracket wiki links are already plain GFM text, so preserve only that exact syntax.
  return markdown.replace(/\\\[\\\[([^\r\n]*?)\\\]\\\]/g, "[[$1]]");
}

export function chatGptHtmlToMarkdown(html: string): string {
  return html.trim() ? preserveObsidianWikiLinks(turndown.turndown(html)).trim() : "";
}

export interface ChatGptMarkdownSegment {
  key: string;
  tag?: string;
  html: string;
  text: string;
  group?: string;
  sourceStart?: number;
  sourceEnd?: number;
  streamable: boolean;
}

interface ChatGptMarkdownCandidate extends ChatGptMarkdownSegment {
  changedAt: number;
  streamableAt?: number;
}

interface CommittedChatGptMarkdownSegment {
  key: string;
  tag?: string;
  text: string;
  sourceStart?: number;
  sourceEnd?: number;
}

export class ChatGptMarkdownConsistencyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatGptMarkdownConsistencyError";
  }
}

/**
 * Converts structurally completed ChatGPT DOM blocks into an append-only Markdown stream.
 *
 * ChatGPT can rewrite old HTML while hydrating citations and controls, so a character prefix is
 * not a safe commit boundary. It can also virtualize an already-rendered prefix, so later DOM
 * snapshots are partial observations rather than the response ledger. The browser supplies source
 * ranges for semantic blocks and marks a block streamable only after a following block exists.
 * Once committed, a missing prefix is harmless; changing text at a committed source range remains
 * an explicit protocol error because Responses deltas cannot be retracted.
 *
 * Source ranges are alignment hints, not a global ordering contract. ChatGPT can expose overlapping,
 * duplicated, or locally-reset ranges while React reparents/hydrates final Markdown. When the
 * visible committed tail proves DOM continuity, ambiguous pending ranges are therefore reconciled
 * by semantic order instead of aborting an otherwise complete response.
 */
export class ChatGptMarkdownBuffer {
  private readonly candidates = new Map<string, ChatGptMarkdownCandidate>();
  private readonly committed: CommittedChatGptMarkdownSegment[] = [];
  private latest: ChatGptMarkdownSegment[] = [];
  private markdown = "";
  private lastGroup: string | undefined;
  private consistencyError: ChatGptMarkdownConsistencyError | undefined;

  constructor(
    private readonly transform: (markdown: string) => string = markdown => markdown,
    private readonly stabilityMs = 750,
  ) {
    if (!Number.isFinite(stabilityMs) || stabilityMs < 0) {
      throw new Error("ChatGPT Markdown stability window must be a non-negative finite number");
    }
  }

  observe(segments: ChatGptMarkdownSegment[], now = Date.now()): string {
    const reconciled = this.reconcile(segments);
    if (reconciled instanceof ChatGptMarkdownConsistencyError) {
      this.consistencyError = reconciled;
      return "";
    }
    this.consistencyError = undefined;
    this.latest = reconciled.map(segment => ({ ...segment }));

    const candidateIds = this.candidateIds(reconciled);
    const visibleCandidates = new Set<string>();
    for (const [index, segment] of reconciled.entries()) {
      const candidateId = candidateIds[index]!;
      visibleCandidates.add(candidateId);
      const previous = this.candidates.get(candidateId);
      const unchanged = previous
        && previous.key === segment.key
        && previous.tag === segment.tag
        && previous.html === segment.html
        && previous.text === segment.text
        && previous.group === segment.group
        && previous.sourceStart === segment.sourceStart
        && previous.sourceEnd === segment.sourceEnd;
      this.candidates.set(candidateId, {
        ...segment,
        changedAt: unchanged ? previous.changedAt : now,
        ...(segment.streamable ? {
          streamableAt: unchanged && previous.streamableAt !== undefined
            ? previous.streamableAt
            : now,
        } : {}),
      });
    }
    for (const candidateId of this.candidates.keys()) {
      if (!visibleCandidates.has(candidateId)) this.candidates.delete(candidateId);
    }

    let delta = "";
    let committedCount = 0;
    while (committedCount < reconciled.length) {
      const candidateId = candidateIds[committedCount]!;
      const candidate = this.candidates.get(candidateId);
      if (!candidate?.streamable || candidate.streamableAt === undefined) break;
      if (now - Math.max(candidate.changedAt, candidate.streamableAt) < this.stabilityMs) break;
      delta += this.commit(candidate);
      this.committed.push(this.committedSegment(candidate));
      this.candidates.delete(candidateId);
      committedCount += 1;
    }
    this.latest = this.latest.slice(committedCount);
    return delta;
  }

  finish(): { markdown: string; delta: string } {
    if (this.consistencyError) throw this.consistencyError;
    let delta = "";
    for (const segment of this.latest) {
      delta += this.commit(segment);
      this.committed.push(this.committedSegment(segment));
    }
    this.candidates.clear();
    this.latest = [];
    return { markdown: this.markdown, delta };
  }

  currentSnapshotIsConsistent(): boolean {
    return this.consistencyError === undefined;
  }

  private reconcile(
    segments: ChatGptMarkdownSegment[],
  ): ChatGptMarkdownSegment[] | ChatGptMarkdownConsistencyError {
    if (this.committed.length === 0 || segments.length === 0) return segments;

    const pending: ChatGptMarkdownSegment[] = [];
    const lastCommittedEnd = this.committed
      .map(segment => segment.sourceEnd)
      .filter((end): end is number => end !== undefined)
      .at(-1);
    const sourceIdentityCounts = new Map<string, number>();
    for (const segment of segments) {
      const identity = this.sourceIdentity(segment);
      if (identity) sourceIdentityCounts.set(identity, (sourceIdentityCounts.get(identity) ?? 0) + 1);
    }
    let highestCommittedIndex = -1;
    let sawPending = false;
    let previousReliablePendingStart: number | undefined;

    for (const segment of segments) {
      const sourceIdentity = this.sourceIdentity(segment);
      const sourceIdentityAmbiguous = sourceIdentity !== undefined
        && (sourceIdentityCounts.get(sourceIdentity) ?? 0) > 1;

      // First protect the append-only ledger. A unique source range still identifies a committed
      // block authoritatively. If ChatGPT duplicated that range in this snapshot, use unique
      // semantic identity instead so the second block cannot be mistaken for the first one.
      const committedIndex = this.committedIndex(segment, !sourceIdentityAmbiguous);
      if (committedIndex !== undefined) {
        const committed = this.committed[committedIndex]!;
        if (sawPending || committedIndex < highestCommittedIndex || committed.text !== segment.text) {
          return this.changedCommittedBlockError();
        }
        highestCommittedIndex = committedIndex;
        continue;
      }

      const overlapsCommittedRange = segment.sourceStart !== undefined
        && lastCommittedEnd !== undefined
        && segment.sourceStart <= lastCommittedEnd;
      const nonMonotonicPendingRange = segment.sourceStart !== undefined
        && previousReliablePendingStart !== undefined
        && segment.sourceStart <= previousReliablePendingStart;
      const sourceRangeReliable = segment.sourceStart !== undefined
        && !sourceIdentityAmbiguous
        && !overlapsCommittedRange
        && !nonMonotonicPendingRange;

      if (sourceRangeReliable) {
        previousReliablePendingStart = segment.sourceStart;
        sawPending = true;
        pending.push(segment);
        continue;
      }

      // Ambiguous ranges can occur when ChatGPT reparents multiple Markdown roots, hydrates
      // citations, or reuses local data-start offsets. If the visible snapshot includes the last
      // committed block, DOM order is enough to prove that everything following it is new pending
      // text. Otherwise require continuity with the previously observed pending tail.
      const followsVisibleCommittedTail = highestCommittedIndex === this.committed.length - 1;
      const alignmentSegment = segment.sourceStart === undefined
        ? segment
        : { ...segment, sourceStart: undefined, sourceEnd: undefined };
      if (!followsVisibleCommittedTail && !this.matchesLatestPending(alignmentSegment)) {
        return new ChatGptMarkdownConsistencyError(
          nonMonotonicPendingRange
            ? "ChatGPT final DOM exposed non-monotonic source ranges"
            : "ChatGPT final DOM could not be aligned with text already streamed to Codex",
        );
      }
      sawPending = true;
      pending.push(segment);
    }

    return pending;
  }

  private sourceIdentity(segment: ChatGptMarkdownSegment): string | undefined {
    return segment.sourceStart !== undefined
      ? `${segment.sourceStart}:${segment.tag ?? ""}`
      : undefined;
  }

  private committedIndex(
    segment: ChatGptMarkdownSegment,
    sourceIdentityReliable = true,
  ): number | undefined {
    if (sourceIdentityReliable) {
      const exact = this.committed.findIndex(committed => (
        segment.sourceStart !== undefined && committed.sourceStart !== undefined
          ? segment.sourceStart === committed.sourceStart && segment.tag === committed.tag
          : segment.key === committed.key
      ));
      if (exact >= 0) return exact;
      if (segment.sourceStart !== undefined) return undefined;
    }

    if (!segment.tag) return undefined;
    const semanticMatches = this.committed
      .map((committed, index) => ({ committed, index }))
      .filter(({ committed }) => committed.tag === segment.tag && committed.text === segment.text);
    return semanticMatches.length === 1 ? semanticMatches[0]!.index : undefined;
  }

  private matchesLatestPending(segment: ChatGptMarkdownSegment): boolean {
    const exact = this.latest.filter(candidate => (
      segment.sourceStart !== undefined && candidate.sourceStart !== undefined
        ? segment.sourceStart === candidate.sourceStart && segment.tag === candidate.tag
        : segment.key === candidate.key
    ));
    if (exact.length === 1) return true;
    if (segment.sourceStart !== undefined) return false;
    if (!segment.tag) return false;
    return this.latest.filter(candidate => (
      candidate.tag === segment.tag && candidate.text === segment.text
    )).length === 1;
  }

  private candidateIds(segments: ChatGptMarkdownSegment[]): string[] {
    const occurrences = new Map<string, number>();
    return segments.map(segment => {
      const base = segment.sourceStart !== undefined
        ? `source:${segment.sourceStart}:${segment.tag ?? ""}`
        : `key:${segment.key}`;
      const occurrence = occurrences.get(base) ?? 0;
      occurrences.set(base, occurrence + 1);
      return occurrence === 0 ? base : `${base}:occurrence:${occurrence}`;
    });
  }

  private committedSegment(segment: ChatGptMarkdownSegment): CommittedChatGptMarkdownSegment {
    return {
      key: segment.key,
      ...(segment.tag ? { tag: segment.tag } : {}),
      text: segment.text,
      ...(segment.sourceStart !== undefined ? { sourceStart: segment.sourceStart } : {}),
      ...(segment.sourceEnd !== undefined ? { sourceEnd: segment.sourceEnd } : {}),
    };
  }

  private changedCommittedBlockError(): ChatGptMarkdownConsistencyError {
    return new ChatGptMarkdownConsistencyError(
      "ChatGPT changed a completed text block that was already streamed to Codex",
    );
  }

  private commit(segment: ChatGptMarkdownSegment): string {
    const block = this.transform(chatGptHtmlToMarkdown(segment.html));
    if (!block) return "";
    const separator = this.markdown
      ? segment.group !== undefined && segment.group === this.lastGroup ? "\n" : "\n\n"
      : "";
    const delta = `${separator}${block}`;
    this.markdown += delta;
    this.lastGroup = segment.group;
    return delta;
  }
}
