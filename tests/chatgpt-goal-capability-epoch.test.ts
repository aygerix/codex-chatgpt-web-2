import { expect, test } from "bun:test";
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
