from pathlib import Path

# 1) Mark a live steer as pending before composer mutation and clear it only after the
# steer attempt settles. The browser worker can then veto completion during the race
# between the old assistant stopping and the steered user turn becoming observable.
p = Path('launcher/electron/live-steering.cjs')
s = p.read_text()
old = '''    const composerSelector = ${JSON.stringify(CHATGPT_COMPOSER_SELECTOR)};\n    const userTurnSelector = ${JSON.stringify(CHATGPT_USER_TURN_SELECTOR)};\n    const text = ${JSON.stringify(text)};\n    const revision = ${JSON.stringify(revision)};\n    const visible = (element) => {'''
new = '''    const composerSelector = ${JSON.stringify(CHATGPT_COMPOSER_SELECTOR)};\n    const userTurnSelector = ${JSON.stringify(CHATGPT_USER_TURN_SELECTOR)};\n    const text = ${JSON.stringify(text)};\n    const revision = ${JSON.stringify(revision)};\n    globalThis.__CODEX_WEB_GPT_STEER_PENDING_REVISION__ = revision;\n    document.documentElement.dataset.codexWebGptSteerPendingRevision = String(revision);\n    const visible = (element) => {'''
if old not in s:
    raise SystemExit('live steer preamble not found')
s = s.replace(old, new, 1)
old = '''    const composers = [...document.querySelectorAll(composerSelector)].filter(visible);\n    if (composers.length !== 1) {\n      throw new Error("ChatGPT steer requires exactly one visible composer");\n    }\n    const composer = composers[0];'''
new = '''    try {\n    const composers = [...document.querySelectorAll(composerSelector)].filter(visible);\n    if (composers.length !== 1) {\n      throw new Error("ChatGPT steer requires exactly one visible composer");\n    }\n    const composer = composers[0];'''
if old not in s:
    raise SystemExit('live steer try insertion point not found')
s = s.replace(old, new, 1)
old = '''    throw new Error("ChatGPT steer send was activated but acceptance was not observed");\n  })()`;'''
new = '''    throw new Error("ChatGPT steer send was activated but acceptance was not observed");\n    } finally {\n      if (globalThis.__CODEX_WEB_GPT_STEER_PENDING_REVISION__ === revision) {\n        delete globalThis.__CODEX_WEB_GPT_STEER_PENDING_REVISION__;\n      }\n      if (document.documentElement.dataset.codexWebGptSteerPendingRevision === String(revision)) {\n        delete document.documentElement.dataset.codexWebGptSteerPendingRevision;\n      }\n    }\n  })()`;'''
if old not in s:
    raise SystemExit('live steer finally insertion point not found')
s = s.replace(old, new, 1)
p.write_text(s)

# 2) Teach the browser worker a two-phase steer state and make completion fail closed
# while a same-turn steer is pending. Re-check after the broker completion fence too.
p = Path('src/adapters/chatgpt-web/browser-worker.ts')
s = p.read_text()
old = '''  private async readCodexSteerRevision(page: Page): Promise<number> {\n    return await page.evaluate(() => {\n      const value = (globalThis as typeof globalThis & { __CODEX_WEB_GPT_STEER_REVISION__?: unknown })\n        .__CODEX_WEB_GPT_STEER_REVISION__;\n      return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : 0;\n    }).catch(() => 0);\n  }'''
new = '''  private async readCodexSteerState(page: Page): Promise<ChatGptCodexSteerState> {\n    return await page.evaluate(() => {\n      const scope = globalThis as typeof globalThis & {\n        __CODEX_WEB_GPT_STEER_REVISION__?: unknown;\n        __CODEX_WEB_GPT_STEER_PENDING_REVISION__?: unknown;\n      };\n      const acceptedValue = scope.__CODEX_WEB_GPT_STEER_REVISION__;\n      const pendingValue = scope.__CODEX_WEB_GPT_STEER_PENDING_REVISION__;\n      const accepted = Number.isSafeInteger(acceptedValue) && Number(acceptedValue) >= 0\n        ? Number(acceptedValue)\n        : 0;\n      const pending = Number.isSafeInteger(pendingValue) && Number(pendingValue) >= 0\n        ? Number(pendingValue)\n        : 0;\n      return { accepted, pending };\n    }).catch(() => ({ accepted: 0, pending: 0 }));\n  }\n\n  private async readCodexSteerRevision(page: Page): Promise<number> {\n    return (await this.readCodexSteerState(page)).accepted;\n  }'''
if old not in s:
    raise SystemExit('readCodexSteerRevision block not found')
s = s.replace(old, new, 1)
anchor = '''export const CHATGPT_SEND_ENABLE_GRACE_MS = 5_000;\n'''
insert = '''export const CHATGPT_SEND_ENABLE_GRACE_MS = 5_000;\n\nexport interface ChatGptCodexSteerState {\n  accepted: number;\n  pending: number;\n}\n\nexport type ChatGptCodexSteerDisposition = "apply" | "wait" | "none";\n\nexport function chatGptCodexSteerDisposition(\n  state: ChatGptCodexSteerState,\n  handledRevision: number,\n): ChatGptCodexSteerDisposition {\n  if (state.accepted > handledRevision) return "apply";\n  if (state.pending > handledRevision) return "wait";\n  return "none";\n}\n'''
if anchor not in s:
    raise SystemExit('worker constant anchor not found')
s = s.replace(anchor, insert, 1)
old = '''        const pendingSteerRevision = await this.readCodexSteerRevision(page);\n        if (pendingSteerRevision > handledSteerRevision) {\n          await applyCodexSteer(pendingSteerRevision);\n          continue;\n        }'''
new = '''        const steerState = await this.readCodexSteerState(page);\n        const steerDisposition = chatGptCodexSteerDisposition(steerState, handledSteerRevision);\n        if (steerDisposition === "apply") {\n          await applyCodexSteer(steerState.accepted);\n          continue;\n        }\n        if (steerDisposition === "wait") {\n          completionFenceRevision = undefined;\n          await new Promise(resolveSleep => setTimeout(resolveSleep, 50));\n          continue;\n        }'''
if old not in s:
    raise SystemExit('top steer check not found')
s = s.replace(old, new, 1)
old = '''            const completionSteerRevision = await this.readCodexSteerRevision(page);\n            if (completionSteerRevision > handledSteerRevision) {\n              await applyCodexSteer(completionSteerRevision);\n              continue;\n            }'''
new = '''            const completionSteerState = await this.readCodexSteerState(page);\n            const completionSteerDisposition = chatGptCodexSteerDisposition(\n              completionSteerState,\n              handledSteerRevision,\n            );\n            if (completionSteerDisposition === "apply") {\n              await applyCodexSteer(completionSteerState.accepted);\n              continue;\n            }\n            if (completionSteerDisposition === "wait") {\n              completionFenceRevision = undefined;\n              await new Promise(resolveSleep => setTimeout(resolveSleep, 50));\n              continue;\n            }'''
if old not in s:
    raise SystemExit('completion steer check not found')
s = s.replace(old, new, 1)
old = '''              if (!await turn.completionFence.commit(completionFenceRevision)) {\n                completionFenceRevision = undefined;\n                responseDomCache.key = undefined;\n                responseDomCache.snapshot = undefined;\n                await new Promise(resolveSleep => setTimeout(resolveSleep, 250));\n                continue;\n              }\n            }\n            if (snapshot.visibleText === "api_tool unavailable") {'''
new = '''              if (!await turn.completionFence.commit(completionFenceRevision)) {\n                completionFenceRevision = undefined;\n                responseDomCache.key = undefined;\n                responseDomCache.snapshot = undefined;\n                await new Promise(resolveSleep => setTimeout(resolveSleep, 250));\n                continue;\n              }\n            }\n            // A live steer can be accepted after the last DOM completion projection but before the\n            // broker fence commits. Re-check after the fence so the old assistant response can never\n            // retire the same-turn helper/token underneath the steered continuation.\n            const postFenceSteerState = await this.readCodexSteerState(page);\n            const postFenceSteerDisposition = chatGptCodexSteerDisposition(\n              postFenceSteerState,\n              handledSteerRevision,\n            );\n            if (postFenceSteerDisposition === "apply") {\n              completionFenceRevision = undefined;\n              await applyCodexSteer(postFenceSteerState.accepted);\n              continue;\n            }\n            if (postFenceSteerDisposition === "wait") {\n              completionFenceRevision = undefined;\n              responseDomCache.key = undefined;\n              responseDomCache.snapshot = undefined;\n              await new Promise(resolveSleep => setTimeout(resolveSleep, 50));\n              continue;\n            }\n            if (snapshot.visibleText === "api_tool unavailable") {'''
if old not in s:
    raise SystemExit('post-fence insertion point not found')
s = s.replace(old, new, 1)
p.write_text(s)

# 3) Update older source-contract assertions to the stronger two-phase steering contract.
p = Path('tests/browser-worker-contract.test.ts')
s = p.read_text()
old = '  expect(workerSource).toContain("completionSteerRevision > handledSteerRevision");\n'
new = '''  expect(workerSource).toContain("__CODEX_WEB_GPT_STEER_PENDING_REVISION__");\n  expect(workerSource).toContain("chatGptCodexSteerDisposition");\n  expect(workerSource).toContain("const postFenceSteerState = await this.readCodexSteerState(page)");\n'''
if old not in s:
    raise SystemExit('old steering source assertion not found')
s = s.replace(old, new, 1)
p.write_text(s)

# 4) Preserve the validated /goal semantics in adapter fixtures: Full-mode browser conversations
# rotate at native-turn boundaries while canonical Codex context carries reasoning continuity.
p = Path('tests/chatgpt-web-harness.test.ts')
s = p.read_text()
s = s.replace(
    'test("keeps sequential native messages in one retained MCP conversation until compaction", async () => {',
    'test("rotates Full-mode retained conversations across native turns while preserving canonical context", async () => {',
    1,
)
old = '''      expect(browserMessages).toBe(2);\n      expect(conversationKeys[0]).toBe(chatGptConversationKey(first, chatGptWebExecutionNamespace(provider))!);\n      expect(conversationKeys[1]).toBe(conversationKeys[0]);\n      expect(tokens[1]).not.toBe(tokens[0]);'''
new = '''      expect(browserMessages).toBe(2);\n      expect(conversationKeys[0]).toBe(chatGptConversationKey(\n        first,\n        chatGptWebExecutionNamespace(provider),\n        { turnScoped: true },\n      )!);\n      expect(conversationKeys[1]).toBe(chatGptConversationKey(\n        second,\n        chatGptWebExecutionNamespace(provider),\n        { turnScoped: true },\n      )!);\n      expect(conversationKeys[1]).not.toBe(conversationKeys[0]);\n      expect(tokens[1]).not.toBe(tokens[0]);'''
if old not in s:
    raise SystemExit('sequential Full-mode fixture block not found')
s = s.replace(old, new, 1)
p.write_text(s)

# 5) Retained compaction fixtures must register the exact source turn's tool-capable conversation
# epoch. Leave the separate pure retained-conversation unit tests alone.
p = Path('tests/retained-compaction.test.ts')
s = p.read_text()
marker = 'test("adapter compact returns one same-agent handoff and preserves a pre-existing ordinary final", async () => {'
start = s.index(marker)
prefix, tail = s[:start], s[start:]
tail = tail.replace(
    'const conversationKey = chatGptConversationKey(sourceRequest, namespace)!;',
    'const conversationKey = chatGptConversationKey(sourceRequest, namespace, { turnScoped: true })!;',
)
tail = tail.replace(
    'conversationKey: chatGptConversationKey(sourceRequest, namespace)!,',
    'conversationKey: chatGptConversationKey(sourceRequest, namespace, { turnScoped: true })!,',
)
tail = tail.replace(
    'expect(chatGptConversationKey(compact, namespace)).toBe(conversationKey);',
    'expect(chatGptConversationKey(compact, namespace, { turnScoped: true })).not.toBe(conversationKey);',
    1,
)
s = prefix + tail
p.write_text(s)

# 6) Focused regression coverage for the completion/steer race.
t = Path('tests/chatgpt-steering-lifecycle.test.ts')
t.write_text(r'''import { expect, test } from "bun:test";
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
''')
