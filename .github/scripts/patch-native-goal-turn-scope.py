from pathlib import Path

p = Path('src/adapters/chatgpt-web/conversation-key.ts')
s = p.read_text()
old_sig = '''export function chatGptConversationKey(
  parsed: CodexParsedRequest,
  namespace: string,
): string | undefined {'''
new_sig = '''export function chatGptConversationKey(
  parsed: CodexParsedRequest,
  namespace: string,
  options: { turnScoped?: boolean } = {},
): string | undefined {'''
if old_sig not in s:
    raise SystemExit('conversation key signature not found')
s = s.replace(old_sig, new_sig, 1)
old_obj = '''    namespace,
    threadId: identity.threadId,
    modelId: parsed.modelId,'''
new_obj = '''    namespace,
    threadId: identity.threadId,
    ...(options.turnScoped ? { turnId: identity.turnId } : {}),
    modelId: parsed.modelId,'''
if old_obj not in s:
    raise SystemExit('conversation key object not found')
s = s.replace(old_obj, new_obj, 1)
p.write_text(s)

p = Path('src/adapters/chatgpt-web/index.ts')
s = p.read_text()
old = '''      ? chatGptConversationKey(checkpointInput.parsed, executionNamespace)
      : undefined;'''
new = '''      ? chatGptConversationKey(checkpointInput.parsed, executionNamespace, {
        // Codex goals are thread-scoped, but Native2 capabilities are turn-scoped. Never retain a
        // tool-capable ChatGPT conversation across native turns: its visible transcript can still
        // contain the previous turn's retired token. Steering within one native turn keeps the same
        // turnId and therefore the same browser conversation/capability epoch.
        turnScoped: mode.localTools,
      })
      : undefined;'''
if old not in s:
    raise SystemExit('conversation key call not found')
s = s.replace(old, new, 1)
p.write_text(s)

t = Path('tests/chatgpt-goal-capability-epoch.test.ts')
t.write_text(r'''import { expect, test } from "bun:test";
import { chatGptConversationKey } from "../src/adapters/chatgpt-web/conversation-key";

function parsed(turnId: string) {
  return {
    modelId: "chatgpt-web/pro",
    options: { reasoning: "xhigh" },
    context: { messages: [] },
    _rawBody: { input: [], metadata: { thread_id: "thread-goal-1", turn_id: turnId } },
  } as any;
}

test("tool-capable retained conversation identity changes across native goal continuation turns", () => {
  const a = chatGptConversationKey(parsed("turn-a"), "ns", { turnScoped: true });
  const b = chatGptConversationKey(parsed("turn-b"), "ns", { turnScoped: true });
  expect(a).toBeTruthy();
  expect(b).toBeTruthy();
  expect(a).not.toBe(b);
});

test("steering inside one native turn keeps the same tool-capable conversation epoch", () => {
  const before = parsed("turn-a");
  const after = parsed("turn-a");
  after.context.messages = [{ role: "user", content: "steer revision" }];
  expect(chatGptConversationKey(before, "ns", { turnScoped: true }))
    .toBe(chatGptConversationKey(after, "ns", { turnScoped: true }));
});

test("read-only retained conversations remain thread-scoped across native turns", () => {
  expect(chatGptConversationKey(parsed("turn-a"), "ns"))
    .toBe(chatGptConversationKey(parsed("turn-b"), "ns"));
});
''')
