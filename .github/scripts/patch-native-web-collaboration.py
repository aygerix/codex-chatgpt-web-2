from pathlib import Path

# Read the configured default child model so an omitted V2 spawn model still has a trustworthy
# cross-backend routing decision.
p = Path('src/codex-integration-document.ts')
s = p.read_text()
old = '''export function readCodexModelContextOverride(): CodexModelContextOverride | undefined {
  const path = getCodexConfigPath();
  if (!existsSync(path)) return undefined;
  const text = readFileSync(path, "utf8");
  const lines = splitLines(text);
  const contextWindow = findTopLevelPositiveInteger(lines, "model_context_window");
  return contextWindow === undefined ? undefined : { contextWindow };
}
'''
new = old + '''\nexport function readCodexDefaultSubagentModel(): string | undefined {
  const path = getCodexConfigPath();
  if (!existsSync(path)) return undefined;
  const assignment = findAgentDefaultSubagentModelAssignment(splitLines(readFileSync(path, "utf8")));
  return assignment.present ? assignment.value : undefined;
}
'''
if old not in s:
    raise SystemExit('model context reader anchor not found')
s = s.replace(old, new, 1)
anchor = '''function setAgentMaxDepth(document: CodexConfigDocument, value: number): void {\n'''
insert = '''export function findAgentDefaultSubagentModelAssignment(lines: string[]): PreviousAssignment {
  const table = findTomlTable(lines, "agents");
  if (!table) return { present: false };
  const regex = assignmentRegex("default_subagent_model");
  const matches: PreviousAssignment[] = [];
  for (let index = table.headerIndex + 1; index < table.endIndex; index += 1) {
    const line = lines[index]!;
    if (/^\\s*#/.test(line)) continue;
    const match = regex.exec(line);
    if (!match) continue;
    matches.push({
      present: true,
      rawLine: line,
      value: decodeTomlString(match[1]!, "default_subagent_model"),
      index,
    });
  }
  if (matches.length > 1) {
    throw new Error("Codex config contains duplicate [agents].default_subagent_model assignments");
  }
  return matches[0] ?? { present: false };
}

'''
if anchor not in s:
    raise SystemExit('agent max depth setter anchor not found')
s = s.replace(anchor, insert + anchor, 1)
p.write_text(s)

p = Path('src/codex-integration.ts')
s = p.read_text()
old = 'export { readCodexModelContextOverride } from "./codex-integration-document";'
new = 'export { readCodexDefaultSubagentModel, readCodexModelContextOverride } from "./codex-integration-document";'
if old not in s:
    raise SystemExit('codex integration export anchor not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Add a narrow SSE translator for official native Codex collaboration calls whose destination is a
# ChatGPT Web child. Native->native calls remain encrypted and byte-semantically untouched.
p = Path('src/native-passthrough.ts')
s = p.read_text()
anchor = '''function endToEndHeaders(source: Headers): Headers {\n'''
insert = r'''export interface NativeCodexPassthroughOptions {
  /** Configured Codex child-model default; used only when spawn_agent omits an explicit model. */
  defaultSubagentModel?: string;
}

interface NativeWebCollaborationContext {
  defaultSubagentModel?: string;
  webTargets: Set<string>;
}

const NATIVE_WEB_PLAINTEXT_COLLABORATION_CALLS = new Set([
  "spawn_agent",
  "send_message",
  "followup_task",
]);

function chatGptWebModel(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("chatgpt-web/");
}

function jsonArguments(value: unknown): JsonObject | undefined {
  if (isObject(value)) return value;
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const parsed: unknown = JSON.parse(value);
    return isObject(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function functionOutputObject(value: unknown): JsonObject | undefined {
  if (isObject(value)) return value;
  const texts: string[] = [];
  if (typeof value === "string") texts.push(value);
  else if (Array.isArray(value)) {
    for (const item of value) {
      if (!isObject(item)) continue;
      const text = item.text;
      if (typeof text === "string") texts.push(text);
    }
  }
  for (const text of texts) {
    try {
      const parsed: unknown = JSON.parse(text);
      if (isObject(parsed)) return parsed;
    } catch {
      // A human-readable tool output is not agent metadata; keep looking.
    }
  }
  return undefined;
}

function collectNativeWebTargets(requestBody: unknown, defaultSubagentModel?: string): Set<string> {
  const targets = new Set<string>();
  if (!isObject(requestBody) || !Array.isArray(requestBody.input)) return targets;
  const webSpawnCalls = new Set<string>();
  for (const raw of requestBody.input) {
    if (!isObject(raw)
      || raw.type !== "function_call"
      || raw.namespace !== "collaboration"
      || raw.name !== "spawn_agent"
      || typeof raw.call_id !== "string") continue;
    const args = jsonArguments(raw.arguments);
    const model = args?.model ?? defaultSubagentModel;
    if (chatGptWebModel(model)) webSpawnCalls.add(raw.call_id);
  }
  for (const raw of requestBody.input) {
    if (!isObject(raw)
      || raw.type !== "function_call_output"
      || typeof raw.call_id !== "string"
      || !webSpawnCalls.has(raw.call_id)) continue;
    const result = functionOutputObject(raw.output);
    if (!result) continue;
    for (const key of ["task_name", "nickname", "agent_id", "thread_id"] as const) {
      const value = result[key];
      if (typeof value === "string" && value.trim()) targets.add(value);
    }
  }
  return targets;
}

function shouldDeliverNativeCollaborationPlaintext(
  call: JsonObject,
  context: NativeWebCollaborationContext,
): boolean {
  if (call.type !== "function_call"
    || call.namespace !== "collaboration"
    || typeof call.name !== "string"
    || !NATIVE_WEB_PLAINTEXT_COLLABORATION_CALLS.has(call.name)) return false;
  const args = jsonArguments(call.arguments);
  if (!args) return false;
  if (call.name === "spawn_agent") {
    return chatGptWebModel(args.model ?? context.defaultSubagentModel);
  }
  const target = args.target;
  return typeof target === "string" && context.webTargets.has(target);
}

/**
 * Mark only Web-targeted V2 collaboration calls for Codex's existing DirectPlaintextMessage path.
 * The native tool router treats an empty encrypted_function_args array as an explicit plaintext
 * delivery marker for collaboration.spawn_agent/send_message/followup_task. We never decrypt,
 * inspect, or alter the ciphertext itself; native->native calls remain exactly as the backend sent
 * them.
 */
export function rewriteNativeCollaborationForWeb(
  value: unknown,
  requestBody: unknown,
  options: NativeCodexPassthroughOptions = {},
): { value: unknown; changed: boolean; calls: string[] } {
  const context: NativeWebCollaborationContext = {
    ...(options.defaultSubagentModel ? { defaultSubagentModel: options.defaultSubagentModel } : {}),
    webTargets: collectNativeWebTargets(requestBody, options.defaultSubagentModel),
  };
  const calls: string[] = [];
  const visit = (candidate: unknown): unknown => {
    if (Array.isArray(candidate)) return candidate.map(visit);
    if (!isObject(candidate)) return candidate;
    let out: JsonObject = candidate;
    if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {
      out = { ...candidate, encrypted_function_args: [] };
      calls.push(String(candidate.name));
    }
    let changedChild = out !== candidate;
    const next: JsonObject = changedChild ? out : { ...candidate };
    for (const [key, child] of Object.entries(out)) {
      const rewritten = visit(child);
      if (rewritten !== child) {
        next[key] = rewritten;
        changedChild = true;
      }
    }
    return changedChild ? next : candidate;
  };
  const rewritten = visit(value);
  return { value: rewritten, changed: rewritten !== value, calls };
}

function transformNativeCollaborationSse(
  body: ReadableStream<Uint8Array>,
  requestBody: unknown,
  options: NativeCodexPassthroughOptions,
): ReadableStream<Uint8Array> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffered = "";
  const transformLine = (line: string): string => {
    const carriage = line.endsWith("\r") ? "\r" : "";
    const clean = carriage ? line.slice(0, -1) : line;
    if (!clean.startsWith("data: ") || clean === SSE_TERMINATOR) return line;
    let payload: unknown;
    try { payload = JSON.parse(clean.slice("data: ".length)); }
    catch { return line; }
    const rewritten = rewriteNativeCollaborationForWeb(payload, requestBody, options);
    if (!rewritten.changed) return line;
    for (const name of [...new Set(rewritten.calls)]) {
      console.info(`[codex-chatgpt-web] native_web_collaboration_plaintext call=${name}`);
    }
    return `data: ${JSON.stringify(rewritten.value)}${carriage}`;
  };
  const transformCompleteLines = (text: string): { output: string; remainder: string } => {
    const lastNewline = text.lastIndexOf("\n");
    if (lastNewline < 0) return { output: "", remainder: text };
    const complete = text.slice(0, lastNewline + 1);
    const remainder = text.slice(lastNewline + 1);
    const output = complete
      .split("\n")
      .slice(0, -1)
      .map(transformLine)
      .join("\n") + "\n";
    return { output, remainder };
  };
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) {
          buffered += decoder.decode();
          if (buffered) controller.enqueue(encoder.encode(transformLine(buffered)));
          controller.close();
          return;
        }
        buffered += decoder.decode(chunk.value, { stream: true });
        const transformed = transformCompleteLines(buffered);
        buffered = transformed.remainder;
        if (!transformed.output) continue;
        controller.enqueue(encoder.encode(transformed.output));
        return;
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
}

'''
if anchor not in s:
    raise SystemExit('native passthrough header anchor not found')
s = s.replace(anchor, insert + anchor, 1)

old = '''export async function forwardNativeCodexRequest(
  request: Request,
  endpoint: NativeCodexEndpoint,
  fetchUpstream: NativeFetch = fetch,
  decodedBody?: unknown,
): Promise<Response> {
'''
new = '''export async function forwardNativeCodexRequest(
  request: Request,
  endpoint: NativeCodexEndpoint,
  fetchUpstream: NativeFetch = fetch,
  decodedBody?: unknown,
  options: NativeCodexPassthroughOptions = {},
): Promise<Response> {
'''
if old not in s:
    raise SystemExit('forwardNative signature not found')
s = s.replace(old, new, 1)

old = '''  let body: BodyInit | undefined;
  if (method === "POST") {
    const parseRequest = decodedBody === undefined ? request.clone() : undefined;
    const originalBody = await request.arrayBuffer();
    const scrubbed = scrubBridgeArtifactsForNative(
      decodedBody === undefined ? await readJsonRequestBody(parseRequest!) : decodedBody,
    );
'''
new = '''  let body: BodyInit | undefined;
  let parsedRequestBody = decodedBody;
  if (method === "POST") {
    const parseRequest = decodedBody === undefined ? request.clone() : undefined;
    const originalBody = await request.arrayBuffer();
    parsedRequestBody = decodedBody === undefined ? await readJsonRequestBody(parseRequest!) : decodedBody;
    const scrubbed = scrubBridgeArtifactsForNative(parsedRequestBody);
'''
if old not in s:
    raise SystemExit('native request body block not found')
s = s.replace(old, new, 1)

old = '''  return new Response(
    upstream.body
      ? withUncleanCloseTolerance(upstream.body, isEventStream, bytes => {
        console.warn(
          `[codex-chatgpt-web] native_upstream_unclean_close endpoint=${endpoint} bytes=${bytes}`
          + " (turn had already completed; closing the client stream normally)",
        );
      })
      : upstream.body,
    {
'''
new = '''  let responseBody = upstream.body
    ? withUncleanCloseTolerance(upstream.body, isEventStream, bytes => {
      console.warn(
        `[codex-chatgpt-web] native_upstream_unclean_close endpoint=${endpoint} bytes=${bytes}`
        + " (turn had already completed; closing the client stream normally)",
      );
    })
    : upstream.body;
  if (responseBody && isEventStream && endpoint === "responses") {
    responseBody = transformNativeCollaborationSse(responseBody, parsedRequestBody, options);
  }
  return new Response(
    responseBody,
    {
'''
if old not in s:
    raise SystemExit('native response body block not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Supply the user's configured default child model to the native response translator.
p = Path('src/server.ts')
s = p.read_text()
old = '''  readCodexModelContextOverride,
  readCodexSubagentProtocol,
  type CodexModelContextOverride,
'''
new = '''  readCodexDefaultSubagentModel,
  readCodexModelContextOverride,
  readCodexSubagentProtocol,
  type CodexModelContextOverride,
'''
if old not in s:
    raise SystemExit('server codex integration import block not found')
s = s.replace(old, new, 1)
old = '''      return await forwardNativeCodexRequest(nativeRequest, "responses", undefined, raw);
'''
new = '''      return await forwardNativeCodexRequest(nativeRequest, "responses", undefined, raw, {
        defaultSubagentModel: readCodexDefaultSubagentModel(),
      });
'''
if old not in s:
    raise SystemExit('server native response passthrough call not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Regression tests for explicit/default Web spawns, native preservation, and follow-up targeting.
p = Path('tests/native-passthrough.test.ts')
s = p.read_text()
addition = r'''

function nativeCollaborationStream(item: Record<string, unknown>): Response {
  const event = {
    type: "response.output_item.done",
    output_index: 0,
    item,
  };
  return new Response(
    `event: response.output_item.done\ndata: ${JSON.stringify(event)}\n\ndata: [DONE]\n\n`,
    { headers: { "content-type": "text/event-stream" } },
  );
}

test("native V2 Web spawn is marked for plaintext delivery without changing its task arguments", async () => {
  const body = {
    model: "gpt-5.6-sol",
    input: [],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const argumentsJson = JSON.stringify({
    message: "inspect package.json",
    task_name: "web-audit",
    model: "chatgpt-web/extra-high",
    reasoning_effort: "xhigh",
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_web_spawn",
      namespace: "collaboration",
      name: "spawn_agent",
      arguments: argumentsJson,
      encrypted_function_args: ["native-ciphertext"],
    })
  ), body);
  const text = await response.text();
  expect(text).toContain(`"arguments":${JSON.stringify(argumentsJson)}`);
  expect(text).toContain('"encrypted_function_args":[]');
  expect(text).not.toContain('native-ciphertext');
});

test("configured Web default marks a native V2 spawn that omits model", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_default_web_spawn",
      namespace: "collaboration",
      name: "spawn_agent",
      arguments: JSON.stringify({ message: "work", task_name: "worker" }),
      encrypted_function_args: ["native-ciphertext"],
    })
  ), body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  expect(await response.text()).toContain('"encrypted_function_args":[]');
});

test("native V2 native-model spawn preserves encrypted delivery", async () => {
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
});

test("native V2 follow-up to a previously spawned Web child is marked plaintext", async () => {
  const spawnArgs = JSON.stringify({
    message: "initial task",
    task_name: "web-worker",
    model: "chatgpt-web/extra-high",
  });
  const body = {
    model: "gpt-5.6-sol",
    input: [
      {
        type: "function_call",
        call_id: "call_prior_spawn",
        namespace: "collaboration",
        name: "spawn_agent",
        arguments: spawnArgs,
        encrypted_function_args: [],
      },
      {
        type: "function_call_output",
        call_id: "call_prior_spawn",
        output: JSON.stringify({ task_name: "web-worker", nickname: "Kepler" }),
      },
    ],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_followup",
      namespace: "collaboration",
      name: "followup_task",
      arguments: JSON.stringify({ target: "web-worker", message: "continue with the second check" }),
      encrypted_function_args: ["native-followup-ciphertext"],
    })
  ), body);
  const text = await response.text();
  expect(text).toContain('"encrypted_function_args":[]');
  expect(text).not.toContain('native-followup-ciphertext');
});

test("native V2 message to an unknown/native child keeps encrypted delivery", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => (
    nativeCollaborationStream({
      type: "function_call",
      call_id: "call_native_message",
      namespace: "collaboration",
      name: "send_message",
      arguments: JSON.stringify({ target: "native-worker", message: "status" }),
      encrypted_function_args: ["native-message-ciphertext"],
    })
  ), body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  expect(await response.text()).toContain('native-message-ciphertext');
});
'''
if 'native V2 Web spawn is marked for plaintext delivery' not in s:
    s += addition
p.write_text(s)

p = Path('tests/codex-integration.test.ts')
s = p.read_text()
old_import = 'import {'
# Add a focused source-level parser test in a new file instead of perturbing this large import list.
p2 = Path('tests/codex-default-subagent-model.test.ts')
p2.write_text('''import { expect, test } from "bun:test";\nimport { findAgentDefaultSubagentModelAssignment } from "../src/codex-integration-document";\n\ntest("reads the configured default Web subagent model from the agents table", () => {\n  expect(findAgentDefaultSubagentModelAssignment([\n    "model = \\\"gpt-5.6-sol\\\"",\n    "[agents]",\n    "default_subagent_model = \\\"chatgpt-web/extra-high\\\"",\n    "max_depth = 2",\n  ])).toMatchObject({ present: true, value: "chatgpt-web/extra-high" });\n});\n\ntest("does not invent a default child model when agents table omits it", () => {\n  expect(findAgentDefaultSubagentModelAssignment(["[agents]", "max_depth = 2"])).toEqual({ present: false });\n});\n''')
