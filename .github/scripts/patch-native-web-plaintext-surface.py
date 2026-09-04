from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("src/native-passthrough.ts")
source = path.read_text()

alias_anchor = '''const NATIVE_WEB_PLAINTEXT_COLLABORATION_CALLS = new Set([\n  "spawn_agent",\n  "send_message",\n  "followup_task",\n]);\n'''
alias_block = alias_anchor + '''\nconst NATIVE_WEB_COLLABORATION_ALIASES = new Map<string, {\n  canonical: "spawn_agent" | "send_message" | "followup_task";\n  plaintext: boolean;\n}>([\n  ["spawn_web_agent", { canonical: "spawn_agent", plaintext: true }],\n  ["spawn_native_agent", { canonical: "spawn_agent", plaintext: false }],\n  ["send_web_message", { canonical: "send_message", plaintext: true }],\n  ["send_native_message", { canonical: "send_message", plaintext: false }],\n  ["followup_web_task", { canonical: "followup_task", plaintext: true }],\n  ["followup_native_task", { canonical: "followup_task", plaintext: false }],\n]);\n\nconst NATIVE_WEB_ALIAS_FOR = {\n  spawn_agent: "spawn_web_agent",\n  send_message: "send_web_message",\n  followup_task: "followup_web_task",\n} as const;\n\nconst NATIVE_ENCRYPTED_ALIAS_FOR = {\n  spawn_agent: "spawn_native_agent",\n  send_message: "send_native_message",\n  followup_task: "followup_native_task",\n} as const;\n'''
source = replace_once(source, alias_anchor, alias_block, "alias constants")

json_args_anchor = '''function jsonArguments(value: unknown): JsonObject | undefined {\n  if (isObject(value)) return value;\n  if (typeof value !== "string" || !value.trim()) return undefined;\n  try {\n    const parsed: unknown = JSON.parse(value);\n    return isObject(parsed) ? parsed : undefined;\n  } catch {\n    return undefined;\n  }\n}\n'''
helpers = json_args_anchor + r'''

function collaborationMessageToolClone(
  tool: JsonObject,
  name: string,
  descriptionPrefix: string,
  plaintext: boolean,
  targetEnum?: readonly string[],
): JsonObject {
  const clone = structuredClone(tool) as JsonObject;
  clone.name = name;
  const priorDescription = typeof clone.description === "string" ? clone.description : "";
  clone.description = `${descriptionPrefix}${priorDescription ? `\n\n${priorDescription}` : ""}`;
  const parameters = isObject(clone.parameters) ? clone.parameters : undefined;
  const properties = parameters && isObject(parameters.properties) ? parameters.properties : undefined;
  if (properties) {
    const message = isObject(properties.message) ? properties.message : undefined;
    if (message && plaintext) delete message.encrypted;
    if (targetEnum && targetEnum.length > 0) {
      const target = isObject(properties.target) ? properties.target : undefined;
      if (target) target.enum = [...targetEnum];
    }
  }
  return clone;
}

function collectNativeTargetsByKind(
  requestBody: unknown,
  defaultSubagentModel: string | undefined,
  wantWeb: boolean,
): Set<string> {
  const targets = new Set<string>();
  if (!isObject(requestBody) || !Array.isArray(requestBody.input)) return targets;
  const matchingSpawnCalls = new Set<string>();
  for (const raw of requestBody.input) {
    if (!isObject(raw)
      || raw.type !== "function_call"
      || raw.namespace !== "collaboration"
      || raw.name !== "spawn_agent"
      || typeof raw.call_id !== "string") continue;
    const args = jsonArguments(raw.arguments);
    const model = args?.model ?? defaultSubagentModel;
    if (chatGptWebModel(model) !== wantWeb) continue;
    matchingSpawnCalls.add(raw.call_id);
    if (typeof args?.task_name === "string" && args.task_name.trim()) targets.add(args.task_name);
  }
  for (const raw of requestBody.input) {
    if (!isObject(raw)
      || raw.type !== "function_call_output"
      || typeof raw.call_id !== "string"
      || !matchingSpawnCalls.has(raw.call_id)) continue;
    const result = functionOutputObject(raw.output);
    if (!result) continue;
    for (const key of ["task_name", "nickname", "agent_id", "thread_id"] as const) {
      const value = result[key];
      if (typeof value === "string" && value.trim()) targets.add(value);
    }
  }
  return targets;
}

/**
 * The native backend encrypts V2 collaboration `message` parameters because Codex marks them with
 * the Responses-only `encrypted` schema keyword. That is correct for a native child, but a Web
 * child cannot decrypt the resulting opaque task. Present a proxy-owned plaintext surface to Sol
 * before inference, then map it back to Codex's canonical collaboration tools on the response.
 *
 * When the configured default child is Web, keep the trained/canonical `spawn_agent` name on the
 * plaintext surface so an ordinary inherited-model spawn cannot accidentally take the encrypted
 * path. Codex's original encrypted surface remains available as `spawn_native_agent`. Once history
 * proves that all known children are Web, do the same for send_message/followup_task. Mixed trees
 * keep the native encrypted canonical names and receive explicit target-constrained Web aliases.
 */
export function rewriteNativeCollaborationToolsForWeb(
  value: unknown,
  options: NativeCodexPassthroughOptions = {},
): { value: unknown; changed: boolean } {
  if (!isObject(value) || !Array.isArray(value.tools)) return { value, changed: false };
  const defaultIsWeb = chatGptWebModel(options.defaultSubagentModel);
  const webTargets = collectNativeTargetsByKind(value, options.defaultSubagentModel, true);
  const nativeTargets = collectNativeTargetsByKind(value, options.defaultSubagentModel, false);
  const webTargetList = [...webTargets].sort();
  let changed = false;
  const tools = value.tools.map(rawNamespace => {
    if (!isObject(rawNamespace)
      || rawNamespace.type !== "namespace"
      || rawNamespace.name !== "collaboration"
      || !Array.isArray(rawNamespace.tools)) return rawNamespace;
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
        if (defaultIsWeb) {
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            "spawn_agent",
            `Cross-backend Web spawn. The configured default child model is ${JSON.stringify(options.defaultSubagentModel)}. Use this canonical tool for an inherited/default child or any model beginning chatgpt-web/. Use spawn_native_agent only for an explicitly native child.`,
            true,
          ));
          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {
            nextTools.push(collaborationMessageToolClone(
              rawTool,
              NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent,
              "Native-only encrypted spawn. Use this instead of spawn_agent when intentionally selecting a non-chatgpt-web model.",
              false,
            ));
          }
        } else {
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            "spawn_agent",
            "Native/inherited encrypted spawn. For any model beginning chatgpt-web/, use spawn_web_agent instead so the child receives a readable plaintext task.",
            false,
          ));
          if (!existingNames.has(NATIVE_WEB_ALIAS_FOR.spawn_agent)) {
            nextTools.push(collaborationMessageToolClone(
              rawTool,
              NATIVE_WEB_ALIAS_FOR.spawn_agent,
              "Web-only cross-backend spawn. REQUIRED for any child model beginning chatgpt-web/. The task message is intentionally plaintext because the Web backend cannot decrypt native collaboration ciphertext.",
              true,
            ));
          }
        }
        changed = true;
        continue;
      }
      if ((name === "send_message" || name === "followup_task") && webTargets.size > 0) {
        const canonical = name as "send_message" | "followup_task";
        const webOnly = nativeTargets.size === 0;
        if (webOnly) {
          const action = canonical === "send_message" ? "message" : "follow-up task";
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            canonical,
            `Cross-backend Web ${action}. All known child targets are Web-backed (${webTargetList.join(", ")}). Use the canonical tool for them; use ${NATIVE_ENCRYPTED_ALIAS_FOR[canonical]} only for an explicitly native target.`,
            true,
            webTargetList,
          ));
          const nativeAlias = NATIVE_ENCRYPTED_ALIAS_FOR[canonical];
          if (!existingNames.has(nativeAlias)) {
            nextTools.push(collaborationMessageToolClone(
              rawTool,
              nativeAlias,
              "Native-only encrypted collaboration message.",
              false,
            ));
          }
        } else {
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            canonical,
            `Native-target encrypted collaboration. For Web targets (${webTargetList.join(", ")}), use ${NATIVE_WEB_ALIAS_FOR[canonical]} instead.`,
            false,
          ));
          const webAlias = NATIVE_WEB_ALIAS_FOR[canonical];
          if (!existingNames.has(webAlias)) {
            nextTools.push(collaborationMessageToolClone(
              rawTool,
              webAlias,
              `Web-only plaintext collaboration for these known targets: ${webTargetList.join(", ")}.`,
              true,
              webTargetList,
            ));
          }
        }
        changed = true;
        continue;
      }
      nextTools.push(rawTool);
    }
    if (!changed) return rawNamespace;
    return { ...rawNamespace, tools: nextTools };
  });
  return changed ? { value: { ...value, tools }, changed: true } : { value, changed: false };
}
'''
source = replace_once(source, json_args_anchor, helpers, "request-side collaboration helpers")

# Replace the old target collector with the generic wrapper so response routing and request planning
# use one model-classification rule.
old_collector_start = source.index("function collectNativeWebTargets(")
old_collector_end = source.index("\nfunction shouldDeliverNativeCollaborationPlaintext(", old_collector_start)
source = source[:old_collector_start] + '''function collectNativeWebTargets(requestBody: unknown, defaultSubagentModel?: string): Set<string> {\n  return collectNativeTargetsByKind(requestBody, defaultSubagentModel, true);\n}\n''' + source[old_collector_end:]

# A canonical spawn_agent is deliberately plaintext when the configured default is Web. Native-only
# aliases are normalized separately and bypass this predicate, so an explicit native alias retains
# Codex's encrypted delivery even in that configuration.
old_spawn_predicate = '''  if (call.name === "spawn_agent") {\n    return chatGptWebModel(args.model ?? context.defaultSubagentModel);\n  }'''
new_spawn_predicate = '''  if (call.name === "spawn_agent") {\n    return chatGptWebModel(context.defaultSubagentModel)\n      || chatGptWebModel(args.model ?? context.defaultSubagentModel);\n  }'''
source = replace_once(source, old_spawn_predicate, new_spawn_predicate, "canonical Web spawn predicate")

old_visit = '''    let out: JsonObject = candidate;\n    if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {\n      out = { ...candidate, encrypted_function_args: [] };\n      calls.push(String(candidate.name));\n    }'''
new_visit = '''    let out: JsonObject = candidate;\n    const alias = candidate.type === "function_call"\n      && candidate.namespace === "collaboration"\n      && typeof candidate.name === "string"\n      ? NATIVE_WEB_COLLABORATION_ALIASES.get(candidate.name)\n      : undefined;\n    if (alias) {\n      out = { ...candidate, name: alias.canonical };\n      if (alias.plaintext) {\n        out.encrypted_function_args = [];\n        calls.push(alias.canonical);\n      }\n    } else if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {\n      out = { ...candidate, encrypted_function_args: [] };\n      calls.push(String(candidate.name));\n    }'''
source = replace_once(source, old_visit, new_visit, "response alias normalization")

old_body = '''    const scrubbed = scrubBridgeArtifactsForNative(parsedRequestBody);\n    if (scrubbed.changed) {\n      headers.delete("content-encoding");\n      body = JSON.stringify(scrubbed.value);\n    } else {\n      body = originalBody;\n    }'''
new_body = '''    const scrubbed = scrubBridgeArtifactsForNative(parsedRequestBody);\n    // Keep the canonical request history for response-side target classification. The upstream\n    // model alone sees the proxy-owned tool aliases; Codex never receives or persists those names.\n    parsedRequestBody = scrubbed.value;\n    const collaborationTools = endpoint === "responses"\n      ? rewriteNativeCollaborationToolsForWeb(scrubbed.value, options)\n      : { value: scrubbed.value, changed: false };\n    if (scrubbed.changed || collaborationTools.changed) {\n      headers.delete("content-encoding");\n      body = JSON.stringify(collaborationTools.value);\n    } else {\n      body = originalBody;\n    }'''
source = replace_once(source, old_body, new_body, "upstream tool-surface rewrite")
path.write_text(source)

# Regression coverage exercises both sides of the bridge: the request schema must make the Web task
# plaintext before inference, and the response must map proxy-only names back to canonical Codex tools.
test_path = Path("tests/native-passthrough.test.ts")
tests = test_path.read_text()
insert = '''\n\ntest("native request gives a Web-default parent a plaintext canonical spawn and preserves a native encrypted alias", async () => {\n  const tool = (name: string) => ({\n    type: "function",\n    name,\n    description: `${name} original`,\n    strict: false,\n    parameters: {\n      type: "object",\n      properties: {\n        task_name: { type: "string" },\n        target: { type: "string" },\n        model: { type: "string" },\n        message: { type: "string", encrypted: true },\n      },\n      additionalProperties: false,\n    },\n  });\n  const body = {\n    model: "gpt-5.6-sol",\n    input: [],\n    tools: [{\n      type: "namespace",\n      name: "collaboration",\n      description: "collab",\n      tools: [tool("spawn_agent"), tool("send_message"), tool("followup_task")],\n    }],\n  };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST",\n    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  let upstreamRequest: Request | undefined;\n  await forwardNativeCodexRequest(request, "responses", async input => {\n    upstreamRequest = input;\n    return nativeCollaborationStream({\n      type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}",\n    });\n  }, body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const forwarded = await upstreamRequest!.json() as { tools: Array<{ name: string; tools: Array<Record<string, any>> }> };\n  const collaboration = forwarded.tools.find(namespace => namespace.name === "collaboration")!;\n  const byName = new Map(collaboration.tools.map(candidate => [candidate.name, candidate]));\n  expect(byName.get("spawn_agent")!.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(byName.get("spawn_agent")!.description).toContain("configured default child model");\n  expect(byName.get("spawn_native_agent")!.parameters.properties.message.encrypted).toBe(true);\n  expect(byName.get("send_message")!.parameters.properties.message.encrypted).toBe(true);\n  expect(byName.has("send_web_message")).toBe(false);\n});\n\ntest("native request with a native default exposes a dedicated plaintext Web spawn alias", async () => {\n  const body = {\n    model: "gpt-5.6-sol", input: [],\n    tools: [{ type: "namespace", name: "collaboration", description: "collab", tools: [{\n      type: "function", name: "spawn_agent", description: "spawn", strict: false,\n      parameters: { type: "object", properties: {\n        task_name: { type: "string" }, model: { type: "string" }, message: { type: "string", encrypted: true },\n      } },\n    }] }],\n  };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  let upstreamRequest: Request | undefined;\n  await forwardNativeCodexRequest(request, "responses", async input => {\n    upstreamRequest = input;\n    return nativeCollaborationStream({ type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}" });\n  }, body, { defaultSubagentModel: "gpt-5.6-sol" });\n  const forwarded = await upstreamRequest!.json() as any;\n  const candidates = forwarded.tools[0].tools;\n  const canonical = candidates.find((candidate: any) => candidate.name === "spawn_agent");\n  const webAlias = candidates.find((candidate: any) => candidate.name === "spawn_web_agent");\n  expect(canonical.parameters.properties.message.encrypted).toBe(true);\n  expect(webAlias.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(webAlias.description).toContain("REQUIRED");\n});\n\ntest("proxy Web spawn alias is normalized to canonical plaintext Codex spawn", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const args = JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: "plain task" });\n  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({\n    type: "function_call", call_id: "web_alias", namespace: "collaboration", name: "spawn_web_agent", arguments: args,\n  }), body, { defaultSubagentModel: "gpt-5.6-sol" });\n  const text = await response.text();\n  expect(text).toContain('"name":"spawn_agent"');\n  expect(text).not.toContain('spawn_web_agent');\n  expect(text).toContain('"encrypted_function_args":[]');\n  expect(text).toContain("plain task");\n});\n\ntest("proxy native spawn alias maps back without stripping native encryption", async () => {\n  const body = { model: "gpt-5.6-sol", input: [] };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },\n    body: JSON.stringify(body),\n  });\n  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({\n    type: "function_call", call_id: "native_alias", namespace: "collaboration", name: "spawn_native_agent",\n    arguments: JSON.stringify({ task_name: "native_worker", model: "gpt-5.6-sol", message: "gAAAAcipher" }),\n    encrypted_function_args: ["native-ciphertext"],\n  }), body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const text = await response.text();\n  expect(text).toContain('"name":"spawn_agent"');\n  expect(text).not.toContain('spawn_native_agent');\n  expect(text).toContain('native-ciphertext');\n  expect(text).not.toContain('"encrypted_function_args":[]');\n});\n\ntest("Web-only child history makes canonical follow-up messaging plaintext before inference", async () => {\n  const priorArgs = JSON.stringify({ task_name: "web_task", model: "chatgpt-web/extra-high", message: "initial" });\n  const tool = (name: string) => ({ type: "function", name, description: name, strict: false, parameters: {\n    type: "object", properties: { target: { type: "string" }, message: { type: "string", encrypted: true } },\n  } });\n  const body = {\n    model: "gpt-5.6-sol",\n    input: [\n      { type: "function_call", call_id: "prior", namespace: "collaboration", name: "spawn_agent", arguments: priorArgs, encrypted_function_args: [] },\n      { type: "function_call_output", call_id: "prior", output: JSON.stringify({ task_name: "web_task", nickname: "Kepler" }) },\n    ],\n    tools: [{ type: "namespace", name: "collaboration", description: "collab", tools: [tool("send_message"), tool("followup_task")] }],\n  };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" }, body: JSON.stringify(body),\n  });\n  let upstreamRequest: Request | undefined;\n  await forwardNativeCodexRequest(request, "responses", async input => {\n    upstreamRequest = input;\n    return nativeCollaborationStream({ type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}" });\n  }, body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const forwarded = await upstreamRequest!.json() as any;\n  const byName = new Map(forwarded.tools[0].tools.map((candidate: any) => [candidate.name, candidate]));\n  expect((byName.get("send_message") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("followup_task") as any).parameters.properties.message).not.toHaveProperty("encrypted");\n  expect((byName.get("send_message") as any).parameters.properties.target.enum).toEqual(["Kepler", "web_task"]);\n  expect((byName.get("send_native_message") as any).parameters.properties.message.encrypted).toBe(true);\n  expect((byName.get("followup_native_task") as any).parameters.properties.message.encrypted).toBe(true);\n});\n\ntest("mixed native and Web children keep encrypted canonical messaging and add a target-constrained Web alias", async () => {\n  const body = {\n    model: "gpt-5.6-sol",\n    input: [\n      { type: "function_call", call_id: "web", namespace: "collaboration", name: "spawn_agent", arguments: JSON.stringify({ task_name: "web_task", model: "chatgpt-web/extra-high", message: "w" }), encrypted_function_args: [] },\n      { type: "function_call_output", call_id: "web", output: JSON.stringify({ task_name: "web_task", nickname: "Kepler" }) },\n      { type: "function_call", call_id: "native", namespace: "collaboration", name: "spawn_agent", arguments: JSON.stringify({ task_name: "native_task", model: "gpt-5.6-sol", message: "gAAAAcipher" }) },\n    ],\n    tools: [{ type: "namespace", name: "collaboration", description: "collab", tools: [{\n      type: "function", name: "send_message", description: "send", strict: false, parameters: { type: "object", properties: {\n        target: { type: "string" }, message: { type: "string", encrypted: true },\n      } },\n    }] }],\n  };\n  const request = new Request("http://127.0.0.1:17841/v1/responses", {\n    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" }, body: JSON.stringify(body),\n  });\n  let upstreamRequest: Request | undefined;\n  await forwardNativeCodexRequest(request, "responses", async input => {\n    upstreamRequest = input;\n    return nativeCollaborationStream({ type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}" });\n  }, body, { defaultSubagentModel: "chatgpt-web/extra-high" });\n  const forwarded = await upstreamRequest!.json() as any;\n  const candidates = forwarded.tools[0].tools;\n  const canonical = candidates.find((candidate: any) => candidate.name === "send_message");\n  const webAlias = candidates.find((candidate: any) => candidate.name === "send_web_message");\n  expect(canonical.parameters.properties.message.encrypted).toBe(true);\n  expect(webAlias.parameters.properties.message).not.toHaveProperty("encrypted");\n  expect(webAlias.parameters.properties.target.enum).toEqual(["Kepler", "web_task"]);\n});\n'''
# Put the new coverage immediately before the reset/stream tests so helpers defined later remain in scope at runtime.
marker = '''\n/** A reset after `data: [DONE]` is a completed stream, while a reset before it is a truncation. */\n'''
if marker not in tests:
    raise SystemExit("test insertion marker not found")
tests = tests.replace(marker, insert + marker, 1)
test_path.write_text(tests)

print("patched native->Web plaintext collaboration surface and regression coverage")
