import { expect, test } from "bun:test";
import {
  ChatGptMarkdownBuffer,
  chatGptHtmlToMarkdown,
  type ChatGptMarkdownSegment,
} from "../src/adapters/chatgpt-web/markdown";

test("turns observed inline file path formats into Markdown links", () => {
  const cases = [
    {
      path: "output/path-format-probe/alpha-notes.md",
      target: "output/path-format-probe/alpha-notes.md",
    },
    {
      path: "output/path-format-probe/beta-report.json",
      target: "output/path-format-probe/beta-report.json",
    },
    {
      path: "/Users/johnmacartew/codex-chatgpt-web/src/path-format-probe/gamma-helper.ts",
      target: "/Users/johnmacartew/codex-chatgpt-web/src/path-format-probe/gamma-helper.ts",
    },
    {
      path: "/Users/johnmacartew/codex-chatgpt-web/output/path-format-probe/epsilon-report.pdf",
      target: "/Users/johnmacartew/codex-chatgpt-web/output/path-format-probe/epsilon-report.pdf",
    },
    {
      path: String.raw`C:\Users\Dev\Documents\Codex\path-format-probe\zeta-result.pdf`,
      target: "C:/Users/Dev/Documents/Codex/path-format-probe/zeta-result.pdf",
    },
    {
      path: "src/adapters/chatgpt-web/markdown.ts:47:3",
      target: "src/adapters/chatgpt-web/markdown.ts:47:3",
    },
  ];

  for (const { path, target } of cases) {
    expect(chatGptHtmlToMarkdown(`<p>Created <code>${path}</code>.</p>`))
      .toBe(`Created [${path}](<${target}>).`);
  }
});

test("preserves inline code that is not an unambiguous file path", () => {
  const html = [
    "<p>",
    "Run <code>bun test tests/example.test.ts</code>, inspect <code>FileChangeItem</code>, ",
    "and retain <code>turn/diff/updated</code>, <code>https://example.com/report.pdf</code>, ",
    "and <code>src/path without-extension</code>, <code>src/.</code>, and <code>src/..</code>.",
    "</p>",
    "<pre><code>src/example.ts</code></pre>",
  ].join("");

  expect(chatGptHtmlToMarkdown(html)).toBe([
    "Run `bun test tests/example.test.ts`, inspect `FileChangeItem`, and retain `turn/diff/updated`, `https://example.com/report.pdf`, and `src/path without-extension`, `src/.`, and `src/..`.",
    "",
    "```",
    "src/example.ts",
    "```",
  ].join("\n"));
});

test("does not nest a generated file link inside an existing link", () => {
  expect(chatGptHtmlToMarkdown(
    '<p>Open <a href="https://example.com/source"><code>src/example.ts</code></a>.</p>',
  )).toBe("Open [`src/example.ts`](https://example.com/source).");
});

function rangedParagraph(
  text: string,
  sourceStart: number,
  sourceEnd: number,
  streamable: boolean,
): ChatGptMarkdownSegment {
  return {
    key: `${sourceStart}:p`,
    tag: "p",
    html: `<p>${text}</p>`,
    text,
    sourceStart,
    sourceEnd,
    streamable,
  };
}

test("final Markdown tolerates a pending source range that moves backward after the committed tail", () => {
  const buffer = new ChatGptMarkdownBuffer(markdown => markdown, 0);

  expect(buffer.observe([
    rangedParagraph("A", 0, 10, true),
    rangedParagraph("B", 20, 30, false),
  ], 0)).toBe("A");

  expect(buffer.observe([
    rangedParagraph("A", 0, 10, true),
    rangedParagraph("B", 20, 30, true),
    rangedParagraph("C", 15, 25, false),
  ], 1)).toBe("\n\nB");

  expect(buffer.currentSnapshotIsConsistent()).toBeTrue();
  expect(buffer.finish().markdown).toBe("A\n\nB\n\nC");
});

test("duplicate pending source starts remain distinct after the first duplicate commits", () => {
  const buffer = new ChatGptMarkdownBuffer(markdown => markdown, 0);

  expect(buffer.observe([
    rangedParagraph("A", 0, 10, true),
    rangedParagraph("B", 20, 30, false),
  ], 0)).toBe("A");

  const duplicated = [
    rangedParagraph("A", 0, 10, true),
    rangedParagraph("B", 20, 30, true),
    rangedParagraph("C", 20, 40, false),
  ];
  expect(buffer.observe(duplicated, 1)).toBe("\n\nB");
  expect(buffer.observe(duplicated, 2)).toBe("");

  expect(buffer.currentSnapshotIsConsistent()).toBeTrue();
  expect(buffer.finish().markdown).toBe("A\n\nB\n\nC");
});

test("ambiguous source ranges still cannot rewrite a block already streamed to Codex", () => {
  const buffer = new ChatGptMarkdownBuffer(markdown => markdown, 0);

  expect(buffer.observe([
    rangedParagraph("A", 0, 10, true),
    rangedParagraph("B", 20, 30, false),
  ], 0)).toBe("A");

  expect(buffer.observe([
    rangedParagraph("A changed", 0, 10, true),
    rangedParagraph("B", 20, 30, false),
  ], 1)).toBe("");

  expect(buffer.currentSnapshotIsConsistent()).toBeFalse();
  expect(() => buffer.finish()).toThrow(
    "ChatGPT changed a completed text block that was already streamed to Codex",
  );
});
