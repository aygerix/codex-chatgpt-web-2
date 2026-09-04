from pathlib import Path

p = Path('src/adapters/chatgpt-web/conversation-key.ts')
s = p.read_text()
s = s.replace(
    'import { extractChatGptTurnIdentity } from "./environment";',
    'import { extractChatGptCompactionSourceRevision, extractChatGptTurnIdentity } from "./environment";',
    1,
)
old_sig = '''export function chatGptConversationKey(
  parsed: CodexParsedRequest,
  namespace: string,
): string | undefined {'''
new_sig = '''export function chatGptConversationKey(
  parsed: CodexParsedRequest,
  namespace: string,
  options: { turnScoped?: boolean; turnId?: string } = {},
): string | undefined {'''
if old_sig not in s:
    raise SystemExit('conversation key signature not found')
s = s.replace(old_sig, new_sig, 1)
old_prelude = '''  const identity = extractChatGptTurnIdentity(parsed);
  if (!identity.threadId) return undefined;
  const raw = parsed._rawBody as { input?: unknown[] } | undefined;'''
new_prelude = '''  const identity = extractChatGptTurnIdentity(parsed);
  if (!identity.threadId) return undefined;
  const scopedTurnId = options.turnScoped ? options.turnId ?? identity.turnId : undefined;
  if (options.turnScoped && !scopedTurnId) return undefined;
  const raw = parsed._rawBody as { input?: unknown[] } | undefined;'''
if old_prelude not in s:
    raise SystemExit('conversation key prelude not found')
s = s.replace(old_prelude, new_prelude, 1)
old_obj = '''    namespace,
    threadId: identity.threadId,
    modelId: parsed.modelId,'''
new_obj = '''    namespace,
    threadId: identity.threadId,
    ...(scopedTurnId ? { turnId: scopedTurnId } : {}),
    modelId: parsed.modelId,'''
if old_obj not in s:
    raise SystemExit('conversation key object not found')
s = s.replace(old_obj, new_obj, 1)
insert_after = '''  })).digest("hex");
}

'''
pos = s.find(insert_after, s.find('export function chatGptConversationKey'))
if pos < 0:
    raise SystemExit('conversation key function end not found')
pos += len(insert_after)
helper = '''/** Locate the retained Full-mode browser epoch owned by the pre-compaction native turn. */
export function chatGptCompactionSourceConversationKey(
  parsed: CodexParsedRequest,
  namespace: string,
): string | undefined {
  const identity = extractChatGptTurnIdentity(parsed);
  const source = extractChatGptCompactionSourceRevision(parsed);
  return chatGptConversationKey(parsed, namespace, {
    turnScoped: true,
    turnId: source.turnId ?? identity.turnId,
  });
}

'''
s = s[:pos] + helper + s[pos:]
p.write_text(s)

p = Path('src/adapters/chatgpt-web/index.ts')
s = p.read_text()
s = s.replace(
'''  chatGptConversationKey,
  retainedConversationResumeRequest,''',
'''  chatGptCompactionSourceConversationKey,
  chatGptConversationKey,
  retainedConversationResumeRequest,''',
1,
)
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
old_source = '              const sourceConversationKey = chatGptConversationKey(parsed, executionNamespace);'
new_source = '              const sourceConversationKey = chatGptCompactionSourceConversationKey(parsed, executionNamespace);'
if old_source not in s:
    raise SystemExit('compaction source conversation key call not found')
s = s.replace(old_source, new_source, 1)
p.write_text(s)

# Update the old retained-turn contract: Full/tool mode now rotates the browser conversation at
# native turn boundaries while preserving same-turn steering and source-addressed compaction.
p = Path('tests/chatgpt-web-harness.test.ts')
s = p.read_text()
s = s.replace(
    'test("keeps sequential native messages in one retained MCP conversation until compaction", async () => {',
    'test("rotates Full-mode retained conversations across native turns while preserving canonical context", async () => {',
    1,
)
s = s.replace(
    '      const prepared = browserMessages === 0 ? await turn.prepare() : await turn.prepareResume!();',
    '      const prepared = await turn.prepare();',
    1,
)
old_expect = '''      expect(browserMessages).toBe(2);
      expect(conversationKeys[0]).toBe(chatGptConversationKey(first, chatGptWebExecutionNamespace(provider))!);
      expect(conversationKeys[1]).toBe(conversationKeys[0]);
      expect(tokens[1]).not.toBe(tokens[0]);
      expect(preparedPrompts[0]).toContain("Inspect the project");
      expect(preparedPrompts[1]).toContain("Continue in the same repository");
      expect(preparedPrompts[1]).not.toContain("First retained answer");
      expect(preparedPrompts[1]).not.toContain(environmentXml);'''
new_expect = '''      expect(browserMessages).toBe(2);
      expect(conversationKeys[0]).toBe(chatGptConversationKey(first, chatGptWebExecutionNamespace(provider), { turnScoped: true })!);
      expect(conversationKeys[1]).toBe(chatGptConversationKey(second, chatGptWebExecutionNamespace(provider), { turnScoped: true })!);
      expect(conversationKeys[1]).not.toBe(conversationKeys[0]);
      expect(tokens[1]).not.toBe(tokens[0]);
      expect(preparedPrompts[0]).toContain("Inspect the project");
      expect(preparedPrompts[1]).toContain("Continue in the same repository");
      expect(preparedPrompts[1]).toContain("First retained answer");
      expect(preparedPrompts[1]).not.toContain(tokens[0]!);'''
if old_expect not in s:
    raise SystemExit('retained MCP expectation block not found')
s = s.replace(old_expect, new_expect, 1)
p.write_text(s)

# Retained compaction fixtures must register the source browser under the same turn-scoped key that
# production Full-mode turns now use. The compaction request itself locates that source via its
# authenticated pre-compaction turn id.
p = Path('tests/retained-compaction.test.ts')
s = p.read_text()
s = s.replace(
'''import {
  chatGptConversationKey,
  retainedConversationResumeRequest,
} from "../src/adapters/chatgpt-web/conversation-key";''',
'''import {
  chatGptCompactionSourceConversationKey,
  chatGptConversationKey,
  retainedConversationResumeRequest,
} from "../src/adapters/chatgpt-web/conversation-key";''',
1,
)
s = s.replace(
    'chatGptConversationKey(sourceRequest, namespace)!',
    'chatGptConversationKey(sourceRequest, namespace, { turnScoped: true })!',
)
s = s.replace(
    '  expect(chatGptConversationKey(compact, namespace)).toBe(conversationKey);',
    '  expect(chatGptCompactionSourceConversationKey(compact, namespace)).toBe(conversationKey);',
    1,
)
p.write_text(s)

# Focused capability-epoch unit tests.
t = Path('tests/chatgpt-goal-capability-epoch.test.ts')
t.write_text(r'''import { expect, test } from "bun:test";
import { chatGptConversationKey } from "../src/adapters/chatgpt-web/conversation-key";

function parsed(turnId: string) {
  return {
    modelId: "chatgpt-web/pro",
    options: { reasoning: "xhigh" },
    context: { messages: [] },
    _rawBody: {
      prompt_cache_key: "thread-goal-1",
      client_metadata: {
        "x-codex-turn-metadata": JSON.stringify({
          thread_id: "thread-goal-1",
          turn_id: turnId,
        }),
      },
      input: [],
    },
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
