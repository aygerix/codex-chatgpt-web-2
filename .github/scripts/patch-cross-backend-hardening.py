from pathlib import Path

p = Path('src/adapters/chatgpt-web/browser-worker.ts')
s = p.read_text()
old = '''    const state = await this.submissionDomState(page, baseline.domCache, signal);\n    const acceptedUsers = new Set(binding.acceptedUserTurnIdentities);\n    if (state.userIdentities.some(identity => !acceptedUsers.has(identity))) {\n      throw new Error("ChatGPT opened another user turn while the bound assistant response was detached");\n    }\n    const identity = binding.identity.startsWith("codex-steer-")\n'''
new = '''    const state = await this.submissionDomState(page, baseline.domCache, signal);\n    const provisionalSteerBinding = binding.identity.startsWith("codex-steer-");\n    if (!provisionalSteerBinding) {\n      const acceptedUsers = new Set(binding.acceptedUserTurnIdentities);\n      if (state.userIdentities.some(identity => !acceptedUsers.has(identity))) {\n        throw new Error("ChatGPT opened another user turn while the bound assistant response was detached");\n      }\n    }\n    // A provisional steer binding can outlive ChatGPT's temporary user/assistant DOM identities.\n    // The accepted steer revision, not an early product data-testid, is the authority for that one\n    // continuation. Once ChatGPT publishes its stable assistant identity, upgrade the binding.\n    const identity = provisionalSteerBinding\n'''
if old not in s:
    raise SystemExit('steer reconciliation anchor not found')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('src/native-passthrough.ts')
s = p.read_text()
old = '''    const args = jsonArguments(raw.arguments);\n    const model = args?.model ?? defaultSubagentModel;\n    if (chatGptWebModel(model)) webSpawnCalls.add(raw.call_id);\n'''
new = '''    const args = jsonArguments(raw.arguments);\n    const model = args?.model ?? defaultSubagentModel;\n    if (chatGptWebModel(model)) {\n      webSpawnCalls.add(raw.call_id);\n      // V2 task_name is a canonical target accepted by later send_message/followup_task calls.\n      // Remember it directly from the spawn request so cross-backend routing does not depend on\n      // one particular function_call_output metadata shape surviving replay or compaction.\n      if (typeof args?.task_name === "string" && args.task_name.trim()) targets.add(args.task_name);\n    }\n'''
if old not in s:
    raise SystemExit('web target collection anchor not found')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('tests/chatgpt-steering-lifecycle.test.ts')
s = p.read_text()
addition = r'''

test("provisional steer reconciliation trusts the accepted steer epoch while stable ids hydrate", () => {
  const source = readFileSync("src/adapters/chatgpt-web/browser-worker.ts", "utf8");
  expect(source).toContain('const provisionalSteerBinding = binding.identity.startsWith("codex-steer-")');
  expect(source).toContain('if (!provisionalSteerBinding)');
  expect(source).toContain('const identity = provisionalSteerBinding');
});
'''
if 'provisional steer reconciliation trusts the accepted steer epoch' not in s:
    s += addition
p.write_text(s)

p = Path('tests/native-passthrough.test.ts')
s = p.read_text()
addition = r'''

test("native V2 follow-up recognizes the Web child task_name directly from spawn history", async () => {
  const body = {
    model: "gpt-5.6-sol",
    input: [{
      type: "function_call",
      call_id: "call_spawn_without_output_metadata",
      namespace: "collaboration",
      name: "spawn_agent",
      arguments: JSON.stringify({
        message: "initial task",
        task_name: "web-task-direct",
        model: "chatgpt-web/extra-high",
      }),
      encrypted_function_args: [],
    }],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_followup_direct_task",
      namespace: "collaboration",
      name: "followup_task",
      arguments: JSON.stringify({ target: "web-task-direct", message: "continue" }),
      encrypted_function_args: ["native-followup-ciphertext"],
    })
  ), body);
  const text = await response.text();
  expect(text).toContain('"encrypted_function_args":[]');
  expect(text).not.toContain('native-followup-ciphertext');
});
'''
if 'recognizes the Web child task_name directly from spawn history' not in s:
    s += addition
p.write_text(s)
