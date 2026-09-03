from pathlib import Path


def once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:180]!r}")
    p.write_text(text.replace(old, new, 1))


path = "src/adapters/chatgpt-web/environment.ts"
once(
    path,
    '''export interface ChatGptThreadSpawnLineage {\n  threadId: string;\n  parentThreadId: string;\n  agentName: string;\n  sandboxType: ChatGptSandboxPolicy["type"];\n  workspaceRoots: string[];\n}''',
    '''export interface ChatGptThreadSpawnLineage {\n  threadId: string;\n  parentThreadId: string;\n  parentTurnId: string;\n  agentName: string;\n  sandboxType: ChatGptSandboxPolicy["type"];\n  workspaceRoots: string[];\n}''',
)

once(
    path,
    '''export function extractChatGptTurnUserRevision(parsed: CodexParsedRequest): unknown {\n  const turnId = extractChatGptTurnIdentity(parsed).turnId;\n  if (!turnId) throw new Error("ChatGPT web requires native Codex turn_id metadata for browser-session replay");\n  const revision = latestChatGptTurnUserRevision(parsed, turnId);\n  if (!revision) throw new Error("ChatGPT web requires a current-turn user message for browser-session replay");\n  if (revision.turnId !== undefined && revision.turnId !== turnId) {\n    throw new Error(CHATGPT_TURN_REVISION_CONFLICT_MESSAGE);\n  }\n  return revision.content;\n}''',
    '''export function extractChatGptTurnUserRevision(parsed: CodexParsedRequest): unknown {\n  const identity = extractChatGptTurnIdentity(parsed);\n  const turnId = identity.turnId;\n  if (!turnId) throw new Error("ChatGPT web requires native Codex turn_id metadata for browser-session replay");\n  const revision = latestChatGptTurnUserRevision(parsed, turnId);\n  if (!revision) throw new Error("ChatGPT web requires a current-turn user message for browser-session replay");\n  if (revision.turnId !== undefined && revision.turnId !== turnId) {\n    // Native Codex stamps a freshly spawned child's first task message with the parent turn that\n    // caused the spawn while the provider request itself already owns the new child turn. Accept\n    // that one mismatch only when the complete canonical thread-spawn lineage proves it exactly.\n    const lineage = extractChatGptThreadSpawnLineage(parsed);\n    const canonicalParentTask = lineage !== undefined\n      && lineage.threadId === identity.threadId\n      && lineage.parentTurnId === revision.turnId;\n    if (!canonicalParentTask) throw new Error(CHATGPT_TURN_REVISION_CONFLICT_MESSAGE);\n  }\n  return revision.content;\n}''',
)

once(
    path,
    '''  const threadId = typeof metadata.thread_id === "string" ? metadata.thread_id.trim() : "";\n  const parentThreadId = typeof metadata.parent_thread_id === "string" ? metadata.parent_thread_id.trim() : "";\n  const agentName = typeof metadata.agent_name === "string" ? metadata.agent_name.trim() : "";\n  if (!threadId || !parentThreadId || threadId === parentThreadId || !/^\\/root\\/.+/.test(agentName)) return undefined;''',
    '''  const threadId = typeof metadata.thread_id === "string" ? metadata.thread_id.trim() : "";\n  const turnId = typeof metadata.turn_id === "string" ? metadata.turn_id.trim() : "";\n  const parentThreadId = typeof metadata.parent_thread_id === "string" ? metadata.parent_thread_id.trim() : "";\n  const parentTurnId = typeof metadata.parent_turn_id === "string" ? metadata.parent_turn_id.trim() : "";\n  const agentName = typeof metadata.agent_name === "string" ? metadata.agent_name.trim() : "";\n  if (!threadId || !turnId || !parentThreadId || !parentTurnId\n    || threadId === parentThreadId || turnId === parentTurnId || !/^\\/root\\/.+/.test(agentName)) return undefined;''',
)

once(
    path,
    '''  return { threadId, parentThreadId, agentName, sandboxType, workspaceRoots };''',
    '''  return { threadId, parentThreadId, parentTurnId, agentName, sandboxType, workspaceRoots };''',
)

path = "tests/environment.test.ts"
once(
    path,
    '''import { extractChatGptTurnEnvironment } from "../src/adapters/chatgpt-web/environment";''',
    '''import {\n  extractChatGptTurnEnvironment,\n  extractChatGptTurnUserRevision,\n} from "../src/adapters/chatgpt-web/environment";''',
)

p = Path(path)
text = p.read_text()
text = text.replace(
    '''          parent_thread_id: "thread_current",\n          agent_name: "/root/read_package_version",''',
    '''          parent_thread_id: "thread_current",\n          parent_turn_id: "turn_current",\n          agent_name: "/root/read_package_version",''',
    1,
)
text = text.replace(
    '''      parent_thread_id: "thread_current",\n      agent_name: "/root/nongit_child",''',
    '''      parent_thread_id: "thread_current",\n      parent_turn_id: "turn_current",\n      agent_name: "/root/nongit_child",''',
    1,
)
text = text.replace(
    '''      parent_thread_id: "thread_current",\n      agent_name: "/root/child",''',
    '''      parent_thread_id: "thread_current",\n      parent_turn_id: "turn_current",\n      agent_name: "/root/child",''',
    1,
)
p.write_text(text)

marker = '''describe("trusted current Codex environment envelope", () => {'''
tests = '''describe("native subagent user revision lineage", () => {\n  function spawnedChildRevision(parentTurnId = "turn_parent", messageTurnId = parentTurnId, subagentKind = "thread_spawn") {\n    const request = currentWire();\n    request._rawBody = {\n      client_metadata: {\n        "x-codex-turn-metadata": JSON.stringify({\n          request_kind: "turn",\n          thread_id: "thread_child",\n          turn_id: "turn_child",\n          parent_thread_id: "thread_parent",\n          parent_turn_id: parentTurnId,\n          agent_name: "/root/subagent_test",\n          subagent_kind: subagentKind,\n          sandbox_mode: "danger-full-access",\n          workspaces: { [root]: { has_changes: false } },\n        }),\n      },\n      input: [{\n        type: "message",\n        id: "msg_child_task",\n        role: "user",\n        content: [{ type: "input_text", text: "Solve the delegated task" }],\n        internal_chat_message_metadata_passthrough: { turn_id: messageTurnId },\n      }],\n    };\n    return request;\n  }\n\n  test("accepts a canonical child task whose message is stamped with its authenticated parent turn", () => {\n    expect(extractChatGptTurnUserRevision(spawnedChildRevision())).toEqual([\n      { type: "input_text", text: "Solve the delegated task" },\n    ]);\n  });\n\n  test("rejects a child task stamped with a turn other than its authenticated parent", () => {\n    expect(() => extractChatGptTurnUserRevision(spawnedChildRevision("turn_parent", "turn_other")))\n      .toThrow("current user message conflicts with native Codex turn_id metadata");\n  });\n\n  test("does not relax turn ownership for a forged non-thread-spawn request", () => {\n    expect(() => extractChatGptTurnUserRevision(spawnedChildRevision("turn_parent", "turn_parent", "other")))\n      .toThrow("current user message conflicts with native Codex turn_id metadata");\n  });\n});\n\n'''
once(path, marker, tests + marker)
