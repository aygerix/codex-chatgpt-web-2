from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

source_path = Path("src/native-passthrough.ts")
source = source_path.read_text()

clone_end = '''  return clone;\n}\n\nfunction collectNativeTargetsByKind('''
clone_helpers = '''  return clone;\n}\n\nfunction requireCollaborationToolParameter(tool: JsonObject, parameter: string): void {\n  const parameters = isObject(tool.parameters) ? tool.parameters : undefined;\n  if (!parameters) return;\n  const required = Array.isArray(parameters.required)\n    ? parameters.required.filter((value): value is string => typeof value === "string")\n    : [];\n  if (!required.includes(parameter)) parameters.required = [...required, parameter];\n}\n\nfunction nativeCollaborationMessageLooksOpaqueCiphertext(call: JsonObject): boolean {\n  const args = jsonArguments(call.arguments);\n  const message = args?.message;\n  // Current native collaboration ciphertext is Fernet-shaped (`gAAAA...`). Do not guess at\n  // decryption or relabel it as plaintext if the upstream backend ignored our proxy schema.\n  return typeof message === "string" && /^gAAAA[A-Za-z0-9_-]{32,}={0,2}$/.test(message);\n}\n\nfunction collectNativeTargetsByKind('''
source = replace_once(source, clone_end, clone_helpers, "helper insertion")

native_alias = '''          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {\n            nextTools.push(collaborationMessageToolClone(\n              rawTool,\n              NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent,\n              "Native-only encrypted spawn. Use this instead of spawn_agent when intentionally selecting a non-chatgpt-web model.",\n              false,\n            ));\n          }'''
native_alias_new = '''          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {\n            const nativeSpawn = collaborationMessageToolClone(\n              rawTool,\n              NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent,\n              "Native-only encrypted spawn. An explicit non-chatgpt-web model is required; omitting model would otherwise inherit the configured Web default.",\n              false,\n            );\n            requireCollaborationToolParameter(nativeSpawn, "model");\n            nextTools.push(nativeSpawn);\n          }'''
source = replace_once(source, native_alias, native_alias_new, "native spawn alias requirement")

web_alias = '''          if (!existingNames.has(NATIVE_WEB_ALIAS_FOR.spawn_agent)) {\n            nextTools.push(collaborationMessageToolClone(\n              rawTool,\n              NATIVE_WEB_ALIAS_FOR.spawn_agent,\n              "Web-only cross-backend spawn. REQUIRED for any child model beginning chatgpt-web/. The task message is intentionally plaintext because the Web backend cannot decrypt native collaboration ciphertext.",\n              true,\n            ));\n          }'''
web_alias_new = '''          if (!existingNames.has(NATIVE_WEB_ALIAS_FOR.spawn_agent)) {\n            const webSpawn = collaborationMessageToolClone(\n              rawTool,\n              NATIVE_WEB_ALIAS_FOR.spawn_agent,\n              "Web-only cross-backend spawn. REQUIRED for any child model beginning chatgpt-web/. An explicit chatgpt-web/... model is required because the configured default is native. The task message is intentionally plaintext because the Web backend cannot decrypt native collaboration ciphertext.",\n              true,\n            );\n            requireCollaborationToolParameter(webSpawn, "model");\n            nextTools.push(webSpawn);\n          }'''
source = replace_once(source, web_alias, web_alias_new, "Web spawn alias requirement")

# Scope mutation per namespace instead of letting one changed namespace affect later namespaces.
old_map = '''  let changed = false;\n  const tools = value.tools.map(rawNamespace => {\n    if (!isObject(rawNamespace)\n      || rawNamespace.type !== "namespace"\n      || rawNamespace.name !== "collaboration"\n      || !Array.isArray(rawNamespace.tools)) return rawNamespace;\n    const existingNames = new Set(rawNamespace.tools'''
new_map = '''  let changed = false;\n  const tools = value.tools.map(rawNamespace => {\n    if (!isObject(rawNamespace)\n      || rawNamespace.type !== "namespace"\n      || rawNamespace.name !== "collaboration"\n      || !Array.isArray(rawNamespace.tools)) return rawNamespace;\n    let namespaceChanged = false;\n    const existingNames = new Set(rawNamespace.tools'''
source = replace_once(source, old_map, new_map, "namespace change scope")
source = source.replace('''        changed = true;\n        continue;''', '''        changed = true;\n        namespaceChanged = true;\n        continue;''')
source = replace_once(source, '''    if (!changed) return rawNamespace;\n    return { ...rawNamespace, tools: nextTools };''', '''    if (!namespaceChanged) return rawNamespace;\n    return { ...rawNamespace, tools: nextTools };''', "namespace return scope")

spawn_pred = '''  if (call.name === "spawn_agent") {\n    return chatGptWebModel(context.defaultSubagentModel)\n      || chatGptWebModel(args.model ?? context.defaultSubagentModel);\n  }'''
spawn_pred_new = '''  if (call.name === "spawn_agent") {\n    if (nativeCollaborationMessageLooksOpaqueCiphertext(call)) return false;\n    return chatGptWebModel(context.defaultSubagentModel)\n      || chatGptWebModel(args.model ?? context.defaultSubagentModel);\n  }'''
source = replace_once(source, spawn_pred, spawn_pred_new, "canonical ciphertext fail-closed")

send_pred = '''  const target = args.target;\n  return typeof target === "string" && context.webTargets.has(target);'''
send_pred_new = '''  if (nativeCollaborationMessageLooksOpaqueCiphertext(call)) return false;\n  const target = args.target;\n  return typeof target === "string" && context.webTargets.has(target);'''
source = replace_once(source, send_pred, send_pred_new, "message ciphertext fail-closed")

alias_block = '''    if (alias) {\n      out = { ...candidate, name: alias.canonical };\n      if (alias.plaintext) {\n        out.encrypted_function_args = [];\n        calls.push(alias.canonical);\n      }\n    } else if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {'''
alias_block_new = '''    if (alias) {\n      out = { ...candidate, name: alias.canonical };\n      if (alias.plaintext && !nativeCollaborationMessageLooksOpaqueCiphertext(candidate)) {\n        out.encrypted_function_args = [];\n        calls.push(alias.canonical);\n      } else if (alias.plaintext) {\n        console.warn(\n          `[codex-chatgpt-web] native_web_collaboration_ciphertext_unrecoverable call=${alias.canonical}`\n          + " (leaving encrypted delivery intact)",\n        );\n      }\n    } else if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {'''
source = replace_once(source, alias_block, alias_block_new, "alias ciphertext fail-closed")

source_path.write_text(source)

test_path = Path("tests/native-passthrough.test.ts")
tests = test_path.read_text()
old_web_default = '''  expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);\n  expect(byName.get("spawn_native_agent")!.parameters.properties).toHaveProperty("model");'''
new_web_default = '''  expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);\n  expect(byName.get("spawn_native_agent")!.parameters.properties).toHaveProperty("model");\n  expect(byName.get("spawn_native_agent")!.parameters.required).toContain("model");'''
tests = replace_once(tests, old_web_default, new_web_default, "native alias test assertion")

old_native_default = '''  expect(canonical.parameters.properties.message.encrypted).toBe(true);\n  expect(webAlias.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(webAlias.description).toContain("REQUIRED");'''
new_native_default = '''  expect(canonical.parameters.properties.message.encrypted).toBe(true);\n  expect(webAlias.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(webAlias.parameters.required).toContain("model");\n  expect(webAlias.description).toContain("REQUIRED");'''
tests = replace_once(tests, old_native_default, new_native_default, "Web alias test assertion")

insert_marker = '''test("proxy Web spawn alias is normalized to canonical plaintext Codex spawn", async () => {'''
new_tests = '''test("opaque native ciphertext targeting Web is never relabeled as plaintext", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST",\n    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const ciphertext = "gAAAAABqmtePV4JnmXa8rCIZ3slT8AIYBvnzsk0NCjpmFBD2Rfy35tmzkBBv0rel5l1WpAXJLbnCpZBIL7BWFm16pcNLX4MPdgcQ0NKN_AE5HMRPr5PjCmMJZPFj1NyhEQ";\n  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({\n    type: "function_call",\n    call_id: "opaque_web_spawn",\n    namespace: "collaboration",\n    name: "spawn_agent",\n    arguments: JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: ciphertext }),\n  }), body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const text = await response.text();\n  expect(text).toContain(ciphertext);\n  expect(text).not.toContain('"encrypted_function_args":[]');\n});\n\ntest("opaque ciphertext returned through the Web alias maps canonical but fails closed", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST",\n    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const ciphertext = "gAAAAABqmsVwfj2W8Z1WLng7ZG13GNpEBFy_-H1oqQont8EWO4GqldqXMGz_n-fT5GWtZSkuenCqvwmzQQCiDz66SvMwMksWJDoD3KtZ5laHtgFAOMfYvM6hGyL9O_EOM";\n  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({\n    type: "function_call",\n    call_id: "opaque_web_alias",\n    namespace: "collaboration",\n    name: "spawn_web_agent",\n    arguments: JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: ciphertext }),\n  }), body, { defaultSubagentModel: "gpt-5.6-sol" });\n  const text = await response.text();\n  expect(text).toContain('"name":"spawn_agent"');\n  expect(text).not.toContain("spawn_web_agent");\n  expect(text).toContain(ciphertext);\n  expect(text).not.toContain('"encrypted_function_args":[]');\n});\n\n''' + insert_marker
if tests.count(insert_marker) != 1:
    raise SystemExit(f"ciphertext tests marker: expected one match, found {tests.count(insert_marker)}")
tests = tests.replace(insert_marker, new_tests, 1)
test_path.write_text(tests)

print("hardened native->Web collaboration model routing and ciphertext fail-closed behavior")
