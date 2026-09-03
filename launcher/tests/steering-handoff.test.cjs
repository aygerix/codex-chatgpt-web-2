const test = require("node:test");
const assert = require("node:assert/strict");
const { completeSteeringHandoff, requestSteeringHandoff } = require("../electron/steering-handoff.cjs");

test("steering reserves and retains the exact running browser conversation", async () => {
  const calls = [];
  const webContents = {
    isDestroyed: () => false,
    executeJavaScript: async () => { calls.push("stop"); return true; },
    setBackgroundThrottling: value => calls.push(["throttle", value]),
  };
  const tab = {
    id: "tab_1",
    traceId: "trace_123456",
    helperPid: 42,
    conversationKey: "a".repeat(64),
    connectorBound: false,
    status: "running",
    loading: true,
    view: { webContents },
  };
  const host = {
    turnTabs: new Map([[tab.id, tab]]),
    syncPowerSaveBlocker: () => calls.push("power"),
    publishState: () => calls.push("publish"),
    writeDescriptor: () => calls.push("descriptor"),
    snapshot: () => ({}),
  };

  const handoff = await requestSteeringHandoff(host, {
    traceId: tab.traceId,
    conversationKey: tab.conversationKey,
    connectorBound: true,
  });
  assert.equal(tab.status, "running");
  assert.equal(handoff.stopRequested, true);

  const completed = completeSteeringHandoff(host, handoff);
  assert.equal(completed.retained, true);
  assert.equal(tab.status, "ready");
  assert.equal(tab.connectorBound, true);
  assert.equal(tab.loading, false);
  assert.ok(calls.includes("stop"));
  assert.ok(calls.includes("power"));
});
