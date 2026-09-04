import { readJsonRequestBody } from "./http-body";
import {
  BRIDGE_COMPACTION_PREFIX,
  SUMMARY_PREFIX,
  decodeCompactionSummary,
} from "./responses/compaction";
import { BRIDGE_REASONING_PREFIX } from "./responses/reasoning-envelope";

const CODEX_BACKEND = "https://chatgpt.com/backend-api/codex";
const FIRST_PARTY_CODEX_ORIGINATORS = new Set([
  "codex_cli_rs",
  "codex-tui",
  "codex_vscode",
  "codex_atlas",
  "codex_chatgpt_desktop",
]);
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

export type NativeFetch = (request: Request) => Promise<Response>;
export type NativeCodexEndpoint = "models" | "responses" | "responses/compact" | "alpha/search";

type JsonObject = Record<string, unknown>;
type BridgeCompactionItem = JsonObject & { type: "compaction"; encrypted_content: string };

function firstPartyCodexOriginator(value: string): boolean {
  return FIRST_PARTY_CODEX_ORIGINATORS.has(value)
    || /^Codex [A-Za-z0-9][A-Za-z0-9._ -]{0,63}$/.test(value);
}

/**
 * Current Codex clients identify themselves as `<originator>/<cargo semver> (...)`. The models
 * backend requires the release-only `major.minor.patch` value even when the client is an alpha.
 * Derive it only from the documented first-party Codex prefix; an arbitrary browser or proxy
 * User-Agent is not evidence of a Codex version and leaves the original request untouched.
 */
export function codexClientVersionFromUserAgent(userAgent: string | null): string | undefined {
  if (!userAgent) return undefined;
  const separator = userAgent.indexOf("/");
  if (separator < 1) return undefined;
  const originator = userAgent.slice(0, separator);
  if (!firstPartyCodexOriginator(originator)) return undefined;
  const version = /^(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:[-+][0-9A-Za-z.-]+)?(?:\s|$)/
    .exec(userAgent.slice(separator + 1));
  return version ? `${version[1]}.${version[2]}.${version[3]}` : undefined;
}

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isBridgeReasoningItem(value: unknown): value is JsonObject {
  if (!isObject(value) || value.type !== "reasoning") return false;
  const encrypted = value.encrypted_content;
  if (typeof encrypted === "string" && encrypted.startsWith(BRIDGE_REASONING_PREFIX)) return true;
  return typeof value.id === "string"
    && /^rs_[0-9a-f]{32}$/i.test(value.id)
    && (encrypted === undefined || encrypted === null)
    && (Array.isArray(value.summary) || Array.isArray(value.content));
}

function isBridgeCompactionItem(value: unknown): value is BridgeCompactionItem {
  return isObject(value)
    && value.type === "compaction"
    && typeof value.encrypted_content === "string"
    && value.encrypted_content.startsWith(BRIDGE_COMPACTION_PREFIX);
}

/**
 * Response item ids are scoped to the backend that created them. A ChatGPT Web response is
 * generated locally, so replaying its `rs_*` id after switching back to native Codex makes the
 * official backend try to load an item it has never stored. The same boundary applies to local
 * `ocx1:` compaction checkpoints: preserve their decoded summary as a normal input message rather
 * than asking the official backend to decrypt a bridge-owned envelope. Once either artifact proves
 * that the history crossed providers, send the complete item content without provider-local ids.
 */
export function scrubBridgeArtifactsForNative(value: unknown): { value: unknown; changed: boolean } {
  if (!isObject(value)
    || !Array.isArray(value.input)
    || !value.input.some(item => isBridgeReasoningItem(item) || isBridgeCompactionItem(item))) {
    return { value, changed: false };
  }

  const input = value.input.flatMap(item => {
    if (!isObject(item)) return [item];
    const clean = { ...item };
    delete clean.id;
    if (isBridgeCompactionItem(clean)) {
      const summary = decodeCompactionSummary(clean.encrypted_content);
      if (summary === null) throw new Error("Invalid ChatGPT Web compaction checkpoint");
      return [{
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: `${SUMMARY_PREFIX}\n\n${summary}` }],
      }];
    }
    if (clean.type !== "reasoning") return [clean];

    if (typeof clean.encrypted_content === "string"
      && clean.encrypted_content.startsWith(BRIDGE_REASONING_PREFIX)) {
      delete clean.encrypted_content;
    } else if (clean.encrypted_content === null) {
      delete clean.encrypted_content;
    }

    const hasSummary = Array.isArray(clean.summary) && clean.summary.length > 0;
    const hasContent = Array.isArray(clean.content) && clean.content.length > 0;
    const hasNativeEncryptedContent = typeof clean.encrypted_content === "string";
    return hasSummary || hasContent || hasNativeEncryptedContent ? [clean] : [];
  });
  const clean: JsonObject = { ...value, input };
  delete clean.previous_response_id;
  return { value: clean, changed: true };
}

export interface NativeCodexPassthroughOptions {
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

const NATIVE_WEB_COLLABORATION_ALIASES = new Map<string, {
  canonical: "spawn_agent" | "send_message" | "followup_task";
  plaintext: boolean;
}>([
  ["spawn_web_agent", { canonical: "spawn_agent", plaintext: true }],
  ["spawn_native_agent", { canonical: "spawn_agent", plaintext: false }],
  ["send_web_message", { canonical: "send_message", plaintext: true }],
  ["send_native_message", { canonical: "send_message", plaintext: false }],
  ["followup_web_task", { canonical: "followup_task", plaintext: true }],
  ["followup_native_task", { canonical: "followup_task", plaintext: false }],
]);

const NATIVE_WEB_ALIAS_FOR = {
  spawn_agent: "spawn_web_agent",
  send_message: "send_web_message",
  followup_task: "followup_web_task",
} as const;

const NATIVE_ENCRYPTED_ALIAS_FOR = {
  spawn_agent: "spawn_native_agent",
  send_message: "send_native_message",
  followup_task: "followup_native_task",
} as const;

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

function requireCollaborationToolParameter(tool: JsonObject, parameter: string): void {
  const parameters = isObject(tool.parameters) ? tool.parameters : undefined;
  if (!parameters) return;
  const required = Array.isArray(parameters.required)
    ? parameters.required.filter((value): value is string => typeof value === "string")
    : [];
  if (!required.includes(parameter)) parameters.required = [...required, parameter];
}

function nativeCollaborationMessageLooksOpaqueCiphertext(call: JsonObject): boolean {
  const args = jsonArguments(call.arguments);
  const message = args?.message;
  // Current native collaboration ciphertext is Fernet-shaped (`gAAAA...`). Do not guess at
  // decryption or relabel it as plaintext if the upstream backend ignored our proxy schema.
  return typeof message === "string" && /^gAAAA[A-Za-z0-9_-]{32,}={0,2}$/.test(message);
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
        if (defaultIsWeb) {
          const canonicalWebSpawn = collaborationMessageToolClone(
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
          if (!existingNames.has(NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent)) {
            const nativeSpawn = collaborationMessageToolClone(
              rawTool,
              NATIVE_ENCRYPTED_ALIAS_FOR.spawn_agent,
              "Native-only encrypted spawn. An explicit non-chatgpt-web model is required; omitting model would otherwise inherit the configured Web default.",
              false,
            );
            requireCollaborationToolParameter(nativeSpawn, "model");
            nextTools.push(nativeSpawn);
          }
        } else {
          nextTools.push(collaborationMessageToolClone(
            rawTool,
            "spawn_agent",
            "Native/inherited encrypted spawn. For any model beginning chatgpt-web/, use spawn_web_agent instead so the child receives a readable plaintext task.",
            false,
          ));
          if (!existingNames.has(NATIVE_WEB_ALIAS_FOR.spawn_agent)) {
            const webSpawn = collaborationMessageToolClone(
              rawTool,
              NATIVE_WEB_ALIAS_FOR.spawn_agent,
              "Web-only cross-backend spawn. REQUIRED for any child model beginning chatgpt-web/. An explicit chatgpt-web/... model is required because the configured default is native. The task message is intentionally plaintext because the Web backend cannot decrypt native collaboration ciphertext.",
              true,
            );
            requireCollaborationToolParameter(webSpawn, "model");
            nextTools.push(webSpawn);
          }
        }
        changed = true;
        namespaceChanged = true;
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
  return collectNativeTargetsByKind(requestBody, defaultSubagentModel, true);
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
    if (nativeCollaborationMessageLooksOpaqueCiphertext(call)) return false;
    return chatGptWebModel(context.defaultSubagentModel)
      || chatGptWebModel(args.model ?? context.defaultSubagentModel);
  }
  if (nativeCollaborationMessageLooksOpaqueCiphertext(call)) return false;
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
    const alias = candidate.type === "function_call"
      && candidate.namespace === "collaboration"
      && typeof candidate.name === "string"
      ? NATIVE_WEB_COLLABORATION_ALIASES.get(candidate.name)
      : undefined;
    if (alias) {
      out = { ...candidate, name: alias.canonical };
      if (alias.plaintext && !nativeCollaborationMessageLooksOpaqueCiphertext(candidate)) {
        out.encrypted_function_args = [];
        calls.push(alias.canonical);
      } else if (alias.plaintext) {
        console.warn(
          `[codex-chatgpt-web] native_web_collaboration_ciphertext_unrecoverable call=${alias.canonical}`
          + " (leaving encrypted delivery intact)",
        );
      }
    } else if (shouldDeliverNativeCollaborationPlaintext(candidate, context)) {
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

function endToEndHeaders(source: Headers): Headers {
  const headers = new Headers();
  for (const [name, value] of source) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) headers.append(name, value);
  }
  headers.delete("content-length");
  return headers;
}

/** Terminator every Responses SSE stream ends with; nothing after it carries meaning. */
const SSE_TERMINATOR = "data: [DONE]";

/**
 * ChatGPT's backend routinely resets the native Codex connection instead of closing it cleanly,
 * which Bun surfaces as ECONNRESET while reading the body. Passed through untouched that reaches
 * Codex as a truncated HTTP body and the opaque "error decoding response body".
 *
 * A reset that arrives after the stream already delivered `data: [DONE]` is an unclean TCP close on
 * a turn that finished: every byte the protocol defines has been forwarded, so the stream is closed
 * normally rather than failed. A reset before that genuinely truncated the turn and is still raised,
 * because inventing a terminal event there would tell Codex a turn ended when it did not.
 */
function withUncleanCloseTolerance(
  body: ReadableStream<Uint8Array>,
  isEventStream: boolean,
  onUncleanClose?: (bytes: number) => void,
): ReadableStream<Uint8Array> {
  if (!isEventStream) return body;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let lineBuffer = "";
  let completed = false;
  let bytes = 0;
  const inspectLines = (text: string): void => {
    lineBuffer += text;
    let newline = lineBuffer.indexOf("\n");
    while (newline >= 0) {
      const line = lineBuffer.slice(0, newline).replace(/\r$/, "");
      lineBuffer = lineBuffer.slice(newline + 1);
      if (line === SSE_TERMINATOR) completed = true;
      newline = lineBuffer.indexOf("\n");
    }
  };
  const inspectTrailingLine = (): void => {
    // A reset can arrive before the final line separator. Treat only an exact unterminated
    // terminator line as complete; text embedded in a JSON data payload must not qualify.
    if (lineBuffer.replace(/\r$/, "") === SSE_TERMINATOR) completed = true;
  };
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          inspectLines(decoder.decode());
          inspectTrailingLine();
          controller.close();
          return;
        }
        bytes += chunk.value.byteLength;
        inspectLines(decoder.decode(chunk.value, { stream: true }));
        controller.enqueue(chunk.value);
      } catch (error) {
        inspectTrailingLine();
        if (!completed) {
          controller.error(error);
          return;
        }
        onUncleanClose?.(bytes);
        controller.close();
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });
}

export async function forwardNativeCodexRequest(
  request: Request,
  endpoint: NativeCodexEndpoint,
  fetchUpstream: NativeFetch = fetch,
  decodedBody?: unknown,
  options: NativeCodexPassthroughOptions = {},
): Promise<Response> {
  const authorization = request.headers.get("authorization") ?? "";
  if (!authorization.startsWith("Bearer ") || authorization.length <= "Bearer ".length) {
    throw new Error("Native Codex passthrough requires the incoming Bearer authorization");
  }

  const incomingUrl = new URL(request.url);
  if (endpoint === "models" && !incomingUrl.searchParams.has("client_version")) {
    const clientVersion = codexClientVersionFromUserAgent(request.headers.get("user-agent"));
    if (clientVersion) incomingUrl.searchParams.set("client_version", clientVersion);
  }
  const headers = endToEndHeaders(request.headers);
  if (endpoint === "models") headers.delete("if-none-match");
  const method = endpoint === "models" ? "GET" : "POST";
  let body: BodyInit | undefined;
  let parsedRequestBody = decodedBody;
  if (method === "POST") {
    const parseRequest = decodedBody === undefined ? request.clone() : undefined;
    const originalBody = await request.arrayBuffer();
    parsedRequestBody = decodedBody === undefined ? await readJsonRequestBody(parseRequest!) : decodedBody;
    const scrubbed = scrubBridgeArtifactsForNative(parsedRequestBody);
    // Keep the canonical request history for response-side target classification. The upstream
    // model alone sees the proxy-owned tool aliases; Codex never receives or persists those names.
    parsedRequestBody = scrubbed.value;
    const collaborationTools = endpoint === "responses"
      ? rewriteNativeCollaborationToolsForWeb(scrubbed.value, options)
      : { value: scrubbed.value, changed: false };
    if (scrubbed.changed || collaborationTools.changed) {
      headers.delete("content-encoding");
      body = JSON.stringify(collaborationTools.value);
    } else {
      body = originalBody;
    }
  }
  const upstreamRequest = new Request(`${CODEX_BACKEND}/${endpoint}${incomingUrl.search}`, {
    method,
    headers,
    ...(body ? { body } : {}),
    signal: request.signal,
  });
  const upstream = await fetchUpstream(upstreamRequest);
  const responseHeaders = endToEndHeaders(upstream.headers);
  const isEventStream = (upstream.headers.get("content-type") ?? "")
    .toLowerCase()
    .includes("text/event-stream");
  let responseBody = upstream.body
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
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    },
  );
}
