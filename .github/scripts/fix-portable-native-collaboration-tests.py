from pathlib import Path

path = Path("tests/native-passthrough.test.ts")
text = path.read_text()

old = '''  expect(text).toContain('\"encrypted_function_args\":[]');\n  expect(text).toContain('\"model\":\"gpt-5.6-sol\"');\n});'''
new = '''  expect(text).toContain('\"encrypted_function_args\":[]');\n  expect(text).toContain('\\\\\"model\\\\\":\\\\\"gpt-5.6-sol\\\\\"');\n});'''
if text.count(old) != 1:
    raise SystemExit(f"native spawn escaping assertion: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)

old = '''test("native V2 message to an unknown/native child keeps encrypted delivery", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST",\n    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const response = await forwardNativeCodexRequest(request, "responses", async () => (\n    nativeCollaborationStream({\n      type: "function_call",\n      call_id: "call_native_message",\n      namespace: "collaboration",\n      name: "send_message",\n      arguments: JSON.stringify({ target: "native-worker", message: "status" }),\n      encrypted_function_args: ["native-message-ciphertext"],\n    })\n  ), body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  expect(await response.text()).toContain('native-message-ciphertext');\n});'''
new = '''test("canonical V2 message to a native child also uses portable plaintext delivery", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST",\n    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const response = await forwardNativeCodexRequest(request, "responses", async () => (\n    nativeCollaborationStream({\n      type: "function_call",\n      call_id: "call_native_message",\n      namespace: "collaboration",\n      name: "send_message",\n      arguments: JSON.stringify({ target: "native-worker", message: "status" }),\n      encrypted_function_args: ["native-message-ciphertext"],\n    })\n  ), body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const result = await response.text();\n  expect(result).toContain('\"encrypted_function_args\":[]');\n  expect(result).not.toContain('native-message-ciphertext');\n});'''
if text.count(old) != 1:
    raise SystemExit(f"canonical native message expectation: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)

path.write_text(text)
print("updated portable collaboration expectations for canonical native delivery")
