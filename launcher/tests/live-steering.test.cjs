const assert = require("node:assert/strict");
const test = require("node:test");
const {
  liveSteerScript,
  steerRunningTurn,
  validateLiveSteerInput,
} = require("../electron/live-steering.cjs");

test("live steering validates the exact bounded control payload", () => {
  assert.deepEqual(validateLiveSteerInput({ traceId: "trace_123", logId: 9, text: "redirect" }), {
    traceId: "trace_123",
    logId: 9,
    text: "redirect",
  });
  assert.throws(() => validateLiveSteerInput({ traceId: "bad", logId: 9, text: "redirect" }), /traceId/);
  assert.throws(() => validateLiveSteerInput({ traceId: "trace_123", logId: 0, text: "redirect" }), /logId/);
  assert.throws(() => validateLiveSteerInput({ traceId: "trace_123", logId: 9, text: "  " }), /empty/);
});

test("the page injection script preserves connector pills and publishes a steer revision only after acceptance", () => {
  const script = liveSteerScript('new direction "now"', 3);
  assert.match(script, /plugin:/);
  assert.match(script, /send-button/);
  assert.match(script, /__CODEX_WEB_GPT_STEER_REVISION__/);
  assert.match(script, /codexWebGptSteerRevision/);
  assert.match(script, /userTurnObserved/);
  assert.ok(script.indexOf("send.click()") < script.indexOf("__CODEX_WEB_GPT_STEER_REVISION__"));
});

test("steering targets only the exact running browser tab and deduplicates a Codex log row", async () => {
  const scripts = [];
  const events = [];
  const tab = {
    traceId: "trace_123",
    status: "running",
    lastHeartbeatAt: 0,
    view: { webContents: {
      isDestroyed: () => false,
      executeJavaScript: async script => {
        scripts.push(script);
        return { accepted: true, userTurnObserved: true };
      },
    } },
  };
  const host = {
    turnTabs: new Map([["tab", tab]]),
    logger: { info: (name, detail) => events.push([name, detail]) },
    publishState: () => {},
    snapshot: () => ({ ok: true }),
  };
  const first = await steerRunningTurn(host, { traceId: "trace_123", logId: 10, text: "first steer" });
  assert.deepEqual(first, { revision: 1, duplicate: false });
  assert.equal(scripts.length, 1);
  assert.equal(tab.steerRevision, 1);
  assert.equal(tab.lastSteerLogId, 10);
  assert.equal(events[0][0], "browser.turn_steered");

  const duplicate = await steerRunningTurn(host, { traceId: "trace_123", logId: 10, text: "first steer" });
  assert.deepEqual(duplicate, { revision: 1, duplicate: true });
  assert.equal(scripts.length, 1);

  await assert.rejects(
    steerRunningTurn(host, { traceId: "other_123", logId: 11, text: "wrong" }),
    /no browser tab owns/,
  );
});


test("launcher control server exposes the authenticated immediate steer route", () => {
  const fs = require("node:fs");
  const source = fs.readFileSync(require.resolve("../electron/control-server.cjs"), "utf8");
  assert.match(source, /\/v1\/turn\/steer/);
  assert.match(source, /steerRunningTurn\(host/);
  assert.match(source, /MAX_STEER_BODY_BYTES/);
});
