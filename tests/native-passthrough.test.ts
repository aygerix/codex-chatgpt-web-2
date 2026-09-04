import { expect, test } from "bun:test";
import { forwardNativeCodexRequest } from "../src/native-passthrough";

test("forwards native Codex requests verbatim to the official backend", async () => {
  const originalBody = Bun.zstdCompressSync(Buffer.from('{"model":"gpt-5.6-sol","stream":true}'));
  const encoded = new ArrayBuffer(originalBody.byteLength);
  new Uint8Array(encoded).set(originalBody);
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
      "content-encoding": "zstd",
      host: "127.0.0.1:17841",
      connection: "keep-alive",
    },
    body: encoded,
  });
  let upstreamUrl = "";
  let upstreamRequest: Request | undefined;
  const response = await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamUrl = input.url;
    upstreamRequest = input;
    return new Response("data: native\n\n", {
      status: 200,
      headers: { "content-type": "text/event-stream", connection: "keep-alive" },
    });
  });

  expect(upstreamUrl).toBe("https://chatgpt.com/backend-api/codex/responses");
  expect(upstreamRequest).toBeDefined();
  expect(upstreamRequest!.headers.get("authorization")).toBe("Bearer codex-oauth-token");
  expect(upstreamRequest!.headers.get("host")).toBeNull();
  expect(upstreamRequest!.headers.get("connection")).toBeNull();
  expect(Buffer.from(await upstreamRequest!.arrayBuffer())).toEqual(Buffer.from(originalBody));
  expect(response.headers.get("content-type")).toContain("text/event-stream");
  expect(response.headers.get("connection")).toBeNull();
  expect(await response.text()).toBe("data: native\n\n");
});

test("forwards native Codex compaction requests to the official compact endpoint", async () => {
  const originalBody = Bun.zstdCompressSync(Buffer.from('{"model":"gpt-5.6-sol","input":[]}'));
  const encoded = new ArrayBuffer(originalBody.byteLength);
  new Uint8Array(encoded).set(originalBody);
  const request = new Request("http://127.0.0.1:17841/v1/responses/compact", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
      "content-encoding": "zstd",
    },
    body: encoded,
  });
  let upstreamUrl = "";
  let upstreamRequest: Request | undefined;
  const response = await forwardNativeCodexRequest(request, "responses/compact", async input => {
    upstreamUrl = input.url;
    upstreamRequest = input;
    return Response.json({ output: [] }, { status: 200 });
  });

  expect(upstreamUrl).toBe("https://chatgpt.com/backend-api/codex/responses/compact");
  expect(upstreamRequest!.headers.get("authorization")).toBe("Bearer codex-oauth-token");
  expect(Buffer.from(await upstreamRequest!.arrayBuffer())).toEqual(Buffer.from(originalBody));
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ output: [] });
});

test("forwards standalone Web Search through the authenticated native Codex route", async () => {
  const body = JSON.stringify({ query: "Codex Web Search passthrough" });
  const request = new Request("http://127.0.0.1:17841/v1/alpha/search?locale=en", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
      host: "127.0.0.1:17841",
    },
    body,
  });
  let upstreamRequest: Request | undefined;
  const response = await forwardNativeCodexRequest(request, "alpha/search", async input => {
    upstreamRequest = input;
    return Response.json({ results: [{ title: "result" }] });
  });

  expect(upstreamRequest!.url).toBe("https://chatgpt.com/backend-api/codex/alpha/search?locale=en");
  expect(upstreamRequest!.method).toBe("POST");
  expect(upstreamRequest!.headers.get("authorization")).toBe("Bearer codex-oauth-token");
  expect(upstreamRequest!.headers.get("host")).toBeNull();
  expect(await upstreamRequest!.text()).toBe(body);
  expect(await response.json()).toEqual({ results: [{ title: "result" }] });
});

test("removes ChatGPT Web item identities before native Codex compaction", async () => {
  const body = {
    model: "gpt-5.6-sol",
    store: false,
    previous_response_id: "resp_local_web_turn",
    input: [
      {
        type: "reasoning",
        id: "rs_2e94d82c29b14b14bb34eae3252fa756",
        summary: [{ type: "summary_text", text: "Pro thinking" }],
        content: null,
        encrypted_content: null,
      },
      {
        type: "reasoning",
        id: "rs_11111111111111111111111111111111",
        summary: [{ type: "summary_text", text: "Bridge envelope reasoning" }],
        encrypted_content: "ocxr1:eyJ0eHQiOiJoaWRkZW4ifQ==",
      },
      {
        type: "message",
        id: "msg_22222222222222222222222222222222",
        role: "assistant",
        content: [{ type: "output_text", text: "Visible answer", annotations: [] }],
      },
      {
        type: "function_call",
        id: "fc_33333333333333333333333333333333",
        call_id: "call_keep_linkage",
        name: "exec_command",
        arguments: "{}",
      },
      { type: "compaction_trigger" },
    ],
  };
  const originalBody = Bun.zstdCompressSync(Buffer.from(JSON.stringify(body)));
  const encoded = new ArrayBuffer(originalBody.byteLength);
  new Uint8Array(encoded).set(originalBody);
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
      "content-encoding": "zstd",
    },
    body: encoded,
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamRequest = input;
    return new Response("data: native\n\n", { headers: { "content-type": "text/event-stream" } });
  }, body);

  expect(upstreamRequest!.headers.get("content-encoding")).toBeNull();
  const forwarded = await upstreamRequest!.json() as {
    previous_response_id?: string;
    input: Array<Record<string, unknown>>;
  };
  expect(forwarded).not.toHaveProperty("previous_response_id");
  expect(forwarded.input.every(item => !("id" in item))).toBe(true);
  expect(forwarded.input.some(item => "encrypted_content" in item
    && typeof item.encrypted_content === "string"
    && item.encrypted_content.startsWith("ocxr1:"))).toBe(false);
  expect(forwarded.input[0]).toMatchObject({
    type: "reasoning",
    summary: [{ type: "summary_text", text: "Pro thinking" }],
  });
  expect(forwarded.input[2]).toMatchObject({
    type: "message",
    role: "assistant",
  });
  expect(forwarded.input[3]).toMatchObject({
    type: "function_call",
    call_id: "call_keep_linkage",
  });
  expect(forwarded.input.at(-1)).toEqual({ type: "compaction_trigger" });
});

test("converts ChatGPT Web compaction checkpoints before switching back to native Codex", async () => {
  const summary = "Keep the verified repository state and continue from the failing test.";
  const body = {
    model: "gpt-5.6-sol",
    previous_response_id: "resp_local_web_compaction",
    input: [
      {
        type: "compaction",
        id: "cmp_11111111111111111111111111111111",
        encrypted_content: `ocx1:${Buffer.from(summary, "utf8").toString("base64")}`,
      },
      {
        type: "compaction",
        id: "cmp_22222222222222222222222222222222",
        encrypted_content: "gAAAAABnative-opaque-compaction",
      },
      {
        type: "message",
        id: "msg_33333333333333333333333333333333",
        role: "user",
        content: [{ type: "input_text", text: "Continue with native Sol." }],
      },
    ],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamRequest = input;
    return new Response("data: native\n\n", { headers: { "content-type": "text/event-stream" } });
  }, body);

  const forwarded = await upstreamRequest!.json() as {
    previous_response_id?: string;
    input: Array<Record<string, unknown>>;
  };
  expect(forwarded).not.toHaveProperty("previous_response_id");
  expect(forwarded.input.every(item => !("id" in item))).toBe(true);
  expect(forwarded.input[0]).toMatchObject({
    type: "message",
    role: "user",
    content: [{
      type: "input_text",
      text: expect.stringContaining(summary),
    }],
  });
  expect(forwarded.input[1]).toEqual({
    type: "compaction",
    encrypted_content: "gAAAAABnative-opaque-compaction",
  });
  expect(JSON.stringify(forwarded)).not.toContain("ocx1:");
});

test("keeps native encrypted reasoning requests byte-for-byte intact", async () => {
  const body = JSON.stringify({
    model: "gpt-5.6-sol",
    input: [{
      type: "reasoning",
      id: "rs_44444444444444444444444444444444",
      summary: [],
      encrypted_content: "gAAAAABnative-opaque-reasoning",
    }],
  });
  const originalBody = Bun.zstdCompressSync(Buffer.from(body));
  const encoded = new ArrayBuffer(originalBody.byteLength);
  new Uint8Array(encoded).set(originalBody);
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: {
      authorization: "Bearer codex-oauth-token",
      "content-type": "application/json",
      "content-encoding": "zstd",
    },
    body: encoded,
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamRequest = input;
    return new Response("data: native\n\n", { headers: { "content-type": "text/event-stream" } });
  });

  expect(upstreamRequest!.headers.get("content-encoding")).toBe("zstd");
  expect(Buffer.from(await upstreamRequest!.arrayBuffer())).toEqual(Buffer.from(originalBody));
});

test("native passthrough fails closed without Codex bearer authentication", async () => {
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });

  await expect(forwardNativeCodexRequest(request, "responses")).rejects.toThrow(
    "Native Codex passthrough requires the incoming Bearer authorization",
  );
});

test("forwards native model discovery as GET and preserves the client version query", async () => {
  const request = new Request("http://127.0.0.1:17841/v1/models?client_version=0.99.0", {
    headers: { authorization: "Bearer codex-oauth-token", "if-none-match": "old-etag" },
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "models", async input => {
    upstreamRequest = input;
    return Response.json({ models: [] });
  });
  expect(upstreamRequest!.url).toBe("https://chatgpt.com/backend-api/codex/models?client_version=0.99.0");
  expect(upstreamRequest!.method).toBe("GET");
  expect(upstreamRequest!.headers.get("if-none-match")).toBeNull();
});

test("repairs a missing models client_version from an exact first-party Codex user agent", async () => {
  const request = new Request("http://127.0.0.1:17841/v1/models", {
    headers: {
      authorization: "Bearer codex-oauth-token",
      "user-agent": "codex_chatgpt_desktop/0.151.0-alpha.7.2 (Mac OS 15.6; arm64) Codex",
    },
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "models", async input => {
    upstreamRequest = input;
    return Response.json({ models: [] });
  });
  expect(upstreamRequest!.url).toBe("https://chatgpt.com/backend-api/codex/models?client_version=0.151.0");
});

test("does not invent a models client version from an unrelated user agent", async () => {
  const request = new Request("http://127.0.0.1:17841/v1/models", {
    headers: {
      authorization: "Bearer codex-oauth-token",
      "user-agent": "Mozilla/5.0 Codex/999.999.999",
    },
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "models", async input => {
    upstreamRequest = input;
    return Response.json({ models: [] });
  });
  expect(upstreamRequest!.url).toBe("https://chatgpt.com/backend-api/codex/models");
});


test("canonical collaboration spawn is portable plaintext under both Web and native defaults", async () => {
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

test("opaque native ciphertext targeting Web is never relabeled as plaintext", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const ciphertext = "gAAAAABqmtePV4JnmXa8rCIZ3slT8AIYBvnzsk0NCjpmFBD2Rfy35tmzkBBv0rel5l1WpAXJLbnCpZBIL7BWFm16pcNLX4MPdgcQ0NKN_AE5HMRPr5PjCmMJZPFj1NyhEQ";
  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({
    type: "function_call",
    call_id: "opaque_web_spawn",
    namespace: "collaboration",
    name: "spawn_agent",
    arguments: JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: ciphertext }),
  }), body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  const text = await response.text();
  expect(text).toContain(ciphertext);
  expect(text).not.toContain('"encrypted_function_args":[]');
});

test("opaque ciphertext returned through the Web alias maps canonical but fails closed", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const ciphertext = "gAAAAABqmsVwfj2W8Z1WLng7ZG13GNpEBFy_-H1oqQont8EWO4GqldqXMGz_n-fT5GWtZSkuenCqvwmzQQCiDz66SvMwMksWJDoD3KtZ5laHtgFAOMfYvM6hGyL9O_EOM";
  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({
    type: "function_call",
    call_id: "opaque_web_alias",
    namespace: "collaboration",
    name: "spawn_web_agent",
    arguments: JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: ciphertext }),
  }), body, { defaultSubagentModel: "gpt-5.6-sol" });
  const text = await response.text();
  expect(text).toContain('"name":"spawn_agent"');
  expect(text).not.toContain("spawn_web_agent");
  expect(text).toContain(ciphertext);
  expect(text).not.toContain('"encrypted_function_args":[]');
});

test("proxy Web spawn alias is normalized to canonical plaintext Codex spawn", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const args = JSON.stringify({ task_name: "web_worker", model: "chatgpt-web/extra-high", message: "plain task" });
  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({
    type: "function_call", call_id: "web_alias", namespace: "collaboration", name: "spawn_web_agent", arguments: args,
  }), body, { defaultSubagentModel: "gpt-5.6-sol" });
  const text = await response.text();
  expect(text).toContain('"name":"spawn_agent"');
  expect(text).not.toContain('spawn_web_agent');
  expect(text).toContain('"encrypted_function_args":[]');
  expect(text).toContain("plain task");
});

test("proxy native spawn alias maps back without stripping native encryption", async () => {
  const body = { model: "gpt-5.6-sol", input: [] };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const response = await forwardNativeCodexRequest(request, "responses", async () => nativeCollaborationStream({
    type: "function_call", call_id: "native_alias", namespace: "collaboration", name: "spawn_native_agent",
    arguments: JSON.stringify({ task_name: "native_worker", model: "gpt-5.6-sol", message: "gAAAAcipher" }),
    encrypted_function_args: ["native-ciphertext"],
  }), body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  const text = await response.text();
  expect(text).toContain('"name":"spawn_agent"');
  expect(text).not.toContain('spawn_native_agent');
  expect(text).toContain('native-ciphertext');
  expect(text).not.toContain('"encrypted_function_args":[]');
});

test("Web-only child history makes canonical follow-up messaging plaintext before inference", async () => {
  const priorArgs = JSON.stringify({ task_name: "web_task", model: "chatgpt-web/extra-high", message: "initial" });
  const tool = (name: string) => ({ type: "function", name, description: name, strict: false, parameters: {
    type: "object", properties: { target: { type: "string" }, message: { type: "string", encrypted: true } },
  } });
  const body = {
    model: "gpt-5.6-sol",
    input: [
      { type: "function_call", call_id: "prior", namespace: "collaboration", name: "spawn_agent", arguments: priorArgs, encrypted_function_args: [] },
      { type: "function_call_output", call_id: "prior", output: JSON.stringify({ task_name: "web_task", nickname: "Kepler" }) },
    ],
    tools: [{ type: "namespace", name: "collaboration", description: "collab", tools: [tool("send_message"), tool("followup_task")] }],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" }, body: JSON.stringify(body),
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamRequest = input;
    return nativeCollaborationStream({ type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}" });
  }, body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  const forwarded = await upstreamRequest!.json() as any;
  const byName = new Map(forwarded.tools[0].tools.map((candidate: any) => [candidate.name, candidate]));
  expect((byName.get("send_message") as any).parameters.properties.message).not.toHaveProperty("encrypted");
  expect((byName.get("followup_task") as any).parameters.properties.message).not.toHaveProperty("encrypted");
  expect((byName.get("send_message") as any).parameters.properties.target).not.toHaveProperty("enum");
  expect(byName.has("send_native_message")).toBe(false);
  expect(byName.has("followup_native_task")).toBe(false);
});

test("mixed native and Web children keep encrypted canonical messaging and add a target-constrained Web alias", async () => {
  const body = {
    model: "gpt-5.6-sol",
    input: [
      { type: "function_call", call_id: "web", namespace: "collaboration", name: "spawn_agent", arguments: JSON.stringify({ task_name: "web_task", model: "chatgpt-web/extra-high", message: "w" }), encrypted_function_args: [] },
      { type: "function_call_output", call_id: "web", output: JSON.stringify({ task_name: "web_task", nickname: "Kepler" }) },
      { type: "function_call", call_id: "native", namespace: "collaboration", name: "spawn_agent", arguments: JSON.stringify({ task_name: "native_task", model: "gpt-5.6-sol", message: "gAAAAcipher" }) },
    ],
    tools: [{ type: "namespace", name: "collaboration", description: "collab", tools: [{
      type: "function", name: "send_message", description: "send", strict: false, parameters: { type: "object", properties: {
        target: { type: "string" }, message: { type: "string", encrypted: true },
      } },
    }] }],
  };
  const request = new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST", headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" }, body: JSON.stringify(body),
  });
  let upstreamRequest: Request | undefined;
  await forwardNativeCodexRequest(request, "responses", async input => {
    upstreamRequest = input;
    return nativeCollaborationStream({ type: "function_call", call_id: "noop", namespace: "collaboration", name: "list_agents", arguments: "{}" });
  }, body, { defaultSubagentModel: "chatgpt-web/extra-high" });
  const forwarded = await upstreamRequest!.json() as any;
  const candidates = forwarded.tools[0].tools;
  const canonical = candidates.find((candidate: any) => candidate.name === "send_message");
  const nativeAlias = candidates.find((candidate: any) => candidate.name === "send_native_message");
  expect(canonical.parameters.properties.message).not.toHaveProperty("encrypted");
  expect(canonical.parameters.properties.target).not.toHaveProperty("enum");
  expect(nativeAlias.parameters.properties.message.encrypted).toBe(true);
  expect(nativeAlias.parameters.properties.target.enum).toEqual(["native_task"]);
  expect(candidates.some((candidate: any) => candidate.name === "send_web_message")).toBe(false);
});

/** A reset after `data: [DONE]` is a completed stream, while a reset before it is a truncation. */
function nativeRequest(): Request {
  return new Request("http://127.0.0.1:17841/v1/responses", {
    method: "POST",
    headers: { authorization: "Bearer codex-oauth-token", "content-type": "application/json" },
    body: '{"model":"gpt-5.6-sol","stream":true}',
  });
}

function resettingEventStream(
  prefix: string[],
  contentType = "text/event-stream",
): Response {
  const encoder = new TextEncoder();
  let sent = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent < prefix.length) {
        controller.enqueue(encoder.encode(prefix[sent]!));
        sent += 1;
        return;
      }
      const reset = new Error("The socket connection was closed unexpectedly");
      (reset as Error & { code?: string }).code = "ECONNRESET";
      controller.error(reset);
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": contentType } });
}

test("an upstream reset after the turn completed closes the client stream normally", async () => {
  const response = await forwardNativeCodexRequest(
    nativeRequest(),
    "responses",
    async () => resettingEventStream([
      'event: response.completed\ndata: {"type":"response.completed"}\n\n',
      "data: [DONE]\n\n",
    ]),
  );

  const body = await response.text();
  expect(body).toContain("response.completed");
  expect(body).toEndWith("data: [DONE]\n\n");
});

test("event-stream media type matching is case-insensitive", async () => {
  const response = await forwardNativeCodexRequest(
    nativeRequest(),
    "responses",
    async () => resettingEventStream(
      ["data: [DONE]\n\n"],
      "Text/Event-Stream; Charset=UTF-8",
    ),
  );

  expect(await response.text()).toBe("data: [DONE]\n\n");
});

test("an upstream reset is not hidden by a [DONE] string inside JSON content", async () => {
  const response = await forwardNativeCodexRequest(
    nativeRequest(),
    "responses",
    async () => resettingEventStream([
      'event: response.output_text.delta\ndata: {"delta":"literal data: [DONE] text"}\n\n',
    ]),
  );

  // The marker is part of the JSON string, not an SSE data line. The upstream reset therefore
  // truncated the turn and must remain visible to the native client.
  await expect(response.text()).rejects.toThrow();
});

test("an upstream reset that truncated the turn is still surfaced as a failure", async () => {
  const response = await forwardNativeCodexRequest(
    nativeRequest(),
    "responses",
    async () => resettingEventStream(['event: response.output_text.delta\ndata: {"delta":"half"}\n\n']),
  );

  await expect(response.text()).rejects.toThrow();
});

test("a non-event-stream body is passed through untouched", async () => {
  const response = await forwardNativeCodexRequest(
    nativeRequest(),
    "responses",
    async () => new Response('{"ok":true}', { status: 200, headers: { "content-type": "application/json" } }),
  );

  expect(await response.text()).toBe('{"ok":true}');
});


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

test("canonical native-model spawn also uses portable plaintext delivery", async () => {
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
  expect(text).toContain('\\"model\\":\\"gpt-5.6-sol\\"');
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

test("canonical V2 message to a native child also uses portable plaintext delivery", async () => {
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
  const result = await response.text();
  expect(result).toContain('"encrypted_function_args":[]');
  expect(result).not.toContain('native-message-ciphertext');
});


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
