from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new: str, label: str) -> str:
    begin = text.find(start)
    if begin < 0:
        raise SystemExit(f"{label}: start marker not found")
    finish = text.find(end, begin)
    if finish < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:begin] + new + text[finish:]

source_path = Path("src/native-passthrough.ts")
source = source_path.read_text()

source = replace_once(
    source,
    '''interface NativeWebCollaborationContext {\n  defaultSubagentModel?: string;\n  webTargets: Set<string>;\n}\n\n''',
    "",
    "remove Web-only collaboration context",
)

source = replace_once(
    source,
    '''const NATIVE_WEB_ALIAS_FOR = {\n  spawn_agent: "spawn_web_agent",\n  send_message: "send_web_message",\n  followup_task: "followup_web_task",\n} as const;\n\n''',
    "",
    "remove request-side Web alias table",
)

portable_tools = r'''export function rewriteNativeCollaborationToolsForWeb(
  value: unknown,
  options: NativeCodexPassthroughOptions = {},
): { value: unknown; changed: boolean } {
  if (!isObject(value) || !Array.isArray(value.tools)) return { value, changed: false };
  const nativeTargets = collectNativeTargetsByKind(value, options.defaultSubagentModel, false);
  const nativeTargetList = [...nativeTargets].sort();
  let changed = false;
  const tools = value.tools.map(rawNamespace => {
    if (!isObject(rawNamespace)
      || rawNamespace.type !== "namespace"
      || rawNamespace.name !== "collaboration"
      || !Array.isArray(rawNamespace.tools)) return rawNamespace;
    let namespaceChanged = false;
    const existingNames = new Set(rawNamespace.tools
      .filter(isObject)
      .map(tool => tool.name)
      .filter((name): name is string => typeof name === "string"));
    const nextTools: unknown[] = [];
    for (const rawTool of rawNamespace.tools) {
      if (!isObject(rawTool) || rawTool.type !== "function" || typeof rawTool.name !== "string") {
        nextTools.push(rawTool);
        continue;
      }
      const name = rawTool.name;
      if (name === "spawn_agent") {
        const portableSpawn = collaborationMessageToolClone(
          rawTool,
          "spawn_agent",
          "Portable collaboration spawn. Use this canonical tool for any child backend, including chatgpt-web/. The task message is intentionally plaintext so cross-backend children can read it. Use spawn_native_agent only when native-only encrypted delivery is explicitly required.",
          true,
        );
        nextTools.push(portableSpawn);
        if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {
          const nativeSpawn = collaborationMessageToolClone(
            rawTool,
            NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent,
            "Native-only encrypted spawn. An explicit non-chatgpt-web model is required. Never use this surface for a chatgpt-web/... child.",
            false,
          );
          requireCollaborationToolParameter(nativeSpawn, "model");
          const parameters = isObject(nativeSpawn.parameters) ? nativeSpawn.parameters : undefined;
          const properties = parameters && isObject(parameters.properties) ? parameters.properties : undefined;
          const model = properties && isObject(properties.model) ? properties.model : undefined;
          if (model) model.pattern = "^(?!chatgpt-web/).+$";
          nextTools.push(nativeSpawn);
        }
        changed = true;
        namespaceChanged = true;
        continue;
      }
      if (name === "send_message" || name === "followup_task") {
        const canonical = name as "send_message" | "followup_task";
        const action = canonical === "send_message" ? "message" : "follow-up task";
        nextTools.push(collaborationMessageToolClone(
          rawTool,
          canonical,
          `Portable plaintext collaboration ${action}. Use this canonical tool for any child backend, including Web.`,
          true,
        ));
        const nativeAlias = NATIVE_ENCRYPTED_ALIAS_FOR[canonical];
        if (nativeTargetList.length > 0 && !existingNames.has(nativeAlias)) {
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            nativeAlias,
            `Native-only encrypted ${action}. This surface is restricted to currently known native child targets.`,
            false,
            nativeTargetList,
          ));
        }
        changed = true;
        namespaceChanged = true;
        continue;
      }
      nextTools.push(rawTool);
    }
    if (!namespaceChanged) return rawNamespace;
    return { ...rawNamespace, tools: nextTools };
  });
  return changed ? { value: { ...value, tools }, changed: true } : { value, changed: false };
}

'''
source = replace_between(
    source,
    "export function rewriteNativeCollaborationToolsForWeb(\n",
    "function functionOutputObject(",
    portable_tools,
    "portable request collaboration surface",
)

portable_delivery = r'''function shouldDeliverNativeCollaborationPlaintext(call: JsonObject): boolean {
  if (call.type !== "function_call"
    || call.namespace !== "collaboration"
    || typeof call.name !== "string"
    || !NATIVE_WEB_PLAINTEXT_COLLABORATION_CALLS.has(call.name)) return false;
  if (!jsonArguments(call.arguments)) return false;
  // The canonical collaboration surface is deliberately portable. The Responses backend should
  // leave its message argument readable because the request-side schema removes the `encrypted`
  // keyword. If it ever returns opaque ciphertext anyway, fail closed rather than falsely stamping
  // ciphertext as DirectPlaintextMessage.
  return !nativeCollaborationMessageLooksOpaqueCiphertext(call);
}

/**
 * Normalize proxy collaboration aliases and mark every readable canonical V2 collaboration
 * message for Codex's existing DirectPlaintextMessage path. This is intentionally backend-neutral:
 * both native and Web children can consume plaintext InterAgentCommunication, while encrypted
 * native-only aliases remain available as an explicit opt-in.
 */
'''
source = replace_between(
    source,
    "function collectNativeWebTargets(",
    "export function rewriteNativeCollaborationForWeb(\n",
    portable_delivery,
    "portable response collaboration predicate",
)

old_context = '''  const context: NativeWebCollaborationContext = {\n    ...(options.defaultSubagentModel ? { defaultSubagentModel: options.defaultSubagentModel } : {}),\n    webTargets: collectNativeWebTargets(requestBody, options.defaultSubagentModel),\n  };\n  const calls: string[] = [];'''
new_context = '''  // Retain the public signature for compatibility with callers and tests; request-side routing now\n  // guarantees that the canonical collaboration message is portable before inference.\n  void requestBody;\n  void options;\n  const calls: string[] = [];'''
source = replace_once(source, old_context, new_context, "remove Web-target response context")
source = replace_once(
    source,
    "    } else if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {",
    "    } else if (shouldDeliverNativeCollaborationPlaintext(candidate)) {",
    "portable response predicate call",
)
source_path.write_text(source)

# Update the request-surface tests to pin the exact live regression: explicit Web selection under a
# native default must still use the familiar canonical spawn_agent with a plaintext message schema.
test_path = Path("tests/native-passthrough.test.ts")
tests = test_path.read_text()

request_tests = r'''test("canonical collaboration spawn is portable plaintext under both Web and native defaults", async () => {
  const tool = (name: string) => ({
    type: "function",
    name,
    description: `${name} original`,
    strict: false,
    parameters: {
      type: "object",
      properties: {
        task_name: { type: "string" },
        target: { type: "string" },
        model: { type: "string" },
        message: { type: "string", encrypted: true },
      },
      additionalProperties: false,
    },
  });
  for (const defaultSubagentModel of ["chatgpt-web/extra-high", "gpt-5.6-sol"]) {
    const body = {
      model: "gpt-5.6-sol",
      input: [],
      tools: [{
        type: "namespace",
        name: "collaboration",
        description: "collab",
        tools: [tool("spawn_agent"), tool("send_message"), tool("followup_task")],
      }],
    };
    const request = new Request("http://127.0.0.1:17841/v1/responses", {
      method: "POST",
      headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    let upstreamRequest: Request | undefined;
    await forwardNativeCodexRequest(request, "responses", async input => {
      upstreamRequest = input;
      return nativeCollaborationStream({
        type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}",
      });
    }, body, { defaultSubagentModel });
    const forwarded = await upstreamRequest!.json() as { tools: Array<{ name: string; tools: Array<Record<string, any>> }> };
    const collaboration = forwarded.tools.find(namespace => namespace.name === "collaboration")!;
    const byName = new Map(collaboration.tools.map(candidate => [candidate.name, candidate]));
    expect(byName.get("spawn_agent")!.parameters.properties.message).not.toHaveProperty("encrypted");
    expect(byName.get("spawn_agent")!.parameters.properties).toHaveProperty("model");
    expect(byName.get("spawn_agent")!.description).toContain("any child backend");
    expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);
    expect(byName.get("spawn_native_agent")!.parameters.required).toContain("model");
    expect(byName.get("spawn_native_agent")!.parameters.properties.model.pattern).toBe("^(?!chatgpt-web/).+$");
    expect(byName.has("spawn_web_agent")).toBe(false);
    expect(byName.get("send_message")!.parameters.properties.message).not.toHaveProperty("encrypted");
    expect(byName.get("followup_task")!.parameters.properties.message).not.toHaveProperty("encrypted");
  }
});

test("explicit Web selection under a native default stays on plaintext canonical spawn_agent", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const args = JSON.stringify({
    task_name: "extra-high-smoke-test",
    model: "chatgpt-web/extra-high",
    reasoning_effort: "xhigh",
    message: "What is 17 * 19? Return only the number.",
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({
    type: "function_call",
    call_id: "call_explicit_web_native_default",
    namespace: "collaboration",
    name: "spawn_agent",
    arguments: args,
  }), body, { defaultSubagentModel: "gpt-5.6-sol" });
  const text = await response.text();
  expect(text).toContain('"name":"spawn_agent"');
  expect(text).toContain("What is 17 * 19?");
  expect(text).toContain('"encrypted_function_args":[]');
});

'''
tests = replace_between(
    tests,
    'test("native request gives a Web-default parent a plaintext canonical spawn and preserves a native encrypted alias", async () => {',
    'test("opaque native ciphertext targeting Web is never relabeled as plaintext", async () => {',
    request_tests,
    "request collaboration tests",
)

# Canonical native spawns are now portable plaintext too. The encrypted path is explicitly named.
old_native_test_start = 'test("native V2 native-model spawn preserves encrypted delivery on the native-default canonical surface", async () => {'
next_test_marker = 'test("native V2 follow-up to a previously spawned Web child is marked plaintext", async () => {'
portable_native_test = r'''test("canonical native-model spawn also uses portable plaintext delivery", async () => {
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
    })
  ), body, { defaultSubagentModel: "gpt-5.6-sol" });
  const text = await response.text();
  expect(text).toContain('"encrypted_function_args":[]');
  expect(text).toContain('"model":"gpt-5.6-sol"');
});

'''
tests = replace_between(tests, old_native_test_start, next_test_marker, portable_native_test, "canonical native plaintext test")

old_web_only = '''  expect((byName.get("send_message") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("followup_task") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("send_message") as any).parameters.properties.target.enum).toEqual(["Kepler", "web_task"]);\n  expect((byName.get("send_native_message") as any).parameters.properties.message.encrypted).toBe(true);\n  expect((byName.get("followup_native_task") as any).parameters.properties.message.encrypted).toBe(true);'''
new_web_only = '''  expect((byName.get("send_message") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("followup_task") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("send_message") as any).parameters.properties.target).not.toHaveProperty("enum");\n  expect(byName.has("send_native_message")).toBe(false);\n  expect(byName.has("followup_native_task")).toBe(false);'''
tests = replace_once(tests, old_web_only, new_web_only, "Web-only portable follow-up assertions")

old_mixed = '''  const canonical = candidates.find((candidate: any) => candidate.name === "send_message");\n  const webAlias = candidates.find((candidate: any) => candidate.name === "send_web_message");\n  expect(canonical.parameters.properties.message.encrypted).toBe(true);\n  expect(webAlias.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(webAlias.parameters.properties.target.enum).toEqual(["Kepler", "web_task"]);'''
new_mixed = '''  const canonical = candidates.find((candidate: any) => candidate.name === "send_message");\n  const nativeAlias = candidates.find((candidate: any) => candidate.name === "send_native_message");\n  expect(canonical.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(canonical.parameters.properties.target).not.toHaveProperty("enum");\n  expect(nativeAlias.parameters.properties.message.encrypted).toBe(true);\n  expect(nativeAlias.parameters.properties.target.enum).toEqual(["native_task"]);\n  expect(candidates.some((candidate: any) => candidate.name === "send_web_message")).toBe(false);'''
tests = replace_once(tests, old_mixed, new_mixed, "mixed portable follow-up assertions")

test_path.write_text(tests)
print("patched canonical V2 collaboration to portable plaintext with guarded native encryption opt-in")
