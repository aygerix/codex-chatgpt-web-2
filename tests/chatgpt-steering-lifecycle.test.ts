import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { chatGptCodexSteerDisposition } from "../src/adapters/chatgpt-web/browser-worker";

test("same-turn steer pending state vetoes completion until acceptance", () => {
  expect(chatGptCodexSteerDisposition({ accepted: 3, pending: 4 }, 3)).toBe("wait");
  expect(chatGptCodexSteerDisposition({ accepted: 4, pending: 0 }, 3)).toBe("apply");
  expect(chatGptCodexSteerDisposition({ accepted: 4, pending: 4 }, 3)).toBe("apply");
  expect(chatGptCodexSteerDisposition({ accepted: 3, pending: 0 }, 3)).toBe("none");
});

test("launcher publishes a pending steer revision before mutating the live composer", () => {
  const source = readFileSync("launcher/electron/live-steering.cjs", "utf8");
  const pending = source.indexOf("__CODEX_WEB_GPT_STEER_PENDING_REVISION__ = revision");
  const insert = source.indexOf('document.execCommand("insertText"');
  const accepted = source.indexOf("__CODEX_WEB_GPT_STEER_REVISION__ = revision");
  expect(pending).toBeGreaterThan(-1);
  expect(insert).toBeGreaterThan(pending);
  expect(accepted).toBeGreaterThan(insert);
  expect(source).toContain("delete globalThis.__CODEX_WEB_GPT_STEER_PENDING_REVISION__");
});

test("browser worker rechecks steer state after the completion fence", () => {
  const source = readFileSync("src/adapters/chatgpt-web/browser-worker.ts", "utf8");
  const commit = source.indexOf("turn.completionFence.commit(completionFenceRevision)");
  const postFence = source.indexOf("const postFenceSteerState = await this.readCodexSteerState(page)");
  const finish = source.indexOf("markdownBuffer.finish()", postFence);
  expect(commit).toBeGreaterThan(-1);
  expect(postFence).toBeGreaterThan(commit);
  expect(finish).toBeGreaterThan(postFence);
});


test("lower-effort steering can bind a semantic assistant before ChatGPT assigns a stable turn id", () => {
  const source = readFileSync("src/adapters/chatgpt-web/browser-worker.ts", "utf8");
  expect(source).toContain('data-codex-web-gpt-steer-assistant-revision');
  expect(source).toContain('`[data-message-author-role="${role}"]`');
  expect(source).toContain('candidate.closest<HTMLElement>("article")');
  expect(source).toContain('const identity = stableIdentity ?? `codex-steer-${revision}`');
  expect(source).toContain('binding.identity.startsWith("codex-steer-")');
  expect(source).toContain('revision,\n          previousUserTurnCount,\n          knownResponseIdentities');
});
