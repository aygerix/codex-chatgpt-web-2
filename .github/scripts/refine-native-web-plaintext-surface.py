from pathlib import Path

source_path = Path("src/native-passthrough.ts")
source = source_path.read_text()
old = '''          nextTools.push(collaborationMessageToolClone(
            rawTool,
            "spawn_agent",
            `Cross-backend Web spawn. The configured default child model is ${JSON.stringify(options.defaultSubagentModel)}. Use this canonical tool for an inherited/default child or any model beginning chatgpt-web/. Use spawn_native_agent only for an explicitly native child.`,
            true,
          ));
          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {'''
new = '''          const canonicalWebSpawn = collaborationMessageToolClone(
            rawTool,
            "spawn_agent",
            `Cross-backend Web spawn. The configured default child model is ${JSON.stringify(options.defaultSubagentModel)}. Use this canonical tool for the inherited/default Web child. Use spawn_native_agent for an explicitly native child.`,
            true,
          );
          const canonicalWebParameters = isObject(canonicalWebSpawn.parameters)
            ? canonicalWebSpawn.parameters
            : undefined;
          const canonicalWebProperties = canonicalWebParameters && isObject(canonicalWebParameters.properties)
            ? canonicalWebParameters.properties
            : undefined;
          // One model-facing function cannot make `message` plaintext only for Web model values.
          // Remove the override entirely on the canonical Web-default surface so the encrypted
          // native route cannot be selected accidentally with plaintext arguments.
          if (canonicalWebProperties) delete canonicalWebProperties.model;
          nextTools.push(canonicalWebSpawn);
          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {'''
if source.count(old) != 1:
    raise SystemExit(f"canonical Web spawn refinement: expected one match, found {source.count(old)}")
source = source.replace(old, new, 1)
source_path.write_text(source)

test_path = Path("tests/native-passthrough.test.ts")
tests = test_path.read_text()
old_assert = '''  expect(byName.get("spawn_agent")!.parameters.properties.message).not.toHaveProperty("encrypted");
  expect(byName.get("spawn_agent")!.description).toContain("configured default child model");
  expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);'''
new_assert = '''  expect(byName.get("spawn_agent")!.parameters.properties.message).not.toHaveProperty("encrypted");
  expect(byName.get("spawn_agent")!.parameters.properties).not.toHaveProperty("model");
  expect(byName.get("spawn_agent")!.description).toContain("configured default child model");
  expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);
  expect(byName.get("spawn_native_agent")!.parameters.properties).toHaveProperty("model");'''
if tests.count(old_assert) != 1:
    raise SystemExit(f"Web-default assertion refinement: expected one match, found {tests.count(old_assert)}")
tests = tests.replace(old_assert, new_assert, 1)

old_test = '''test("native V2 native-model spawn preserves encrypted delivery", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_native_spawn",
      namespace: "collaboration",
      name: "spawn_agent",
      arguments: JSON.stringify({ message: "work", task_name: "worker", model: "gpt-5.6-sol" }),
      encrypted_function_args: ["native-ciphertext"],
    })
  ), body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  const text = await response.text();
  expect(text).toContain('native-ciphertext');
  expect(text).not.toContain('"encrypted_function_args":[]');
});'''
new_test = '''test("native V2 native-model spawn preserves encrypted delivery on the native-default canonical surface", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_native_spawn",
      namespace: "collaboration",
      name: "spawn_agent",
      arguments: JSON.stringify({ message: "work", task_name: "worker", model: "gpt-5.6-sol" }),
      encrypted_function_args: ["native-ciphertext"],
    })
  ), body, { defaultSubagentModel: "gpt-5.6-sol" });
  const text = await response.text();
  expect(text).toContain('native-ciphertext');
  expect(text).not.toContain('"encrypted_function_args":[]');
});'''
if tests.count(old_test) != 1:
    raise SystemExit(f"native canonical regression refinement: expected one match, found {tests.count(old_test)}")
tests = tests.replace(old_test, new_test, 1)
test_path.write_text(tests)

print("refined Web-default canonical spawn to exclude native model override")
