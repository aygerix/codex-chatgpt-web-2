const CHATGPT_STOP_BUTTON_SELECTOR = '[data-testid="stop-button"]';

function ownedTurnTab(host, traceId, conversationKey) {
  if (!(host?.turnTabs instanceof Map)) throw new Error("browser turn registry is unavailable");
  const tab = [...host.turnTabs.values()].find(candidate => candidate.traceId === traceId);
  if (!tab) throw new Error(`Browser turn ownership mismatch: no browser tab owns ${traceId}`);
  if (tab.status !== "running") throw new Error(`Browser turn ${traceId} is no longer running`);
  if (tab.conversationKey !== conversationKey) {
    throw new Error(`Browser turn ${traceId} does not own the requested steering conversation`);
  }
  return tab;
}

async function requestSteeringHandoff(host, { traceId, conversationKey, connectorBound }) {
  const tab = ownedTurnTab(host, traceId, conversationKey);
  const contents = tab.view?.webContents;
  let stopRequested = false;
  if (contents && !contents.isDestroyed()) {
    stopRequested = await contents.executeJavaScript(`(() => {
      const candidates = [...document.querySelectorAll(${JSON.stringify(CHATGPT_STOP_BUTTON_SELECTOR)})];
      const stop = candidates.find(element => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return element.isConnected && rect.width > 0 && rect.height > 0
          && style.display !== "none" && style.visibility !== "hidden";
      });
      if (!(stop instanceof HTMLElement)) return false;
      stop.click();
      return true;
    })()`, true).catch(() => false);
  }
  return {
    traceId,
    helperPid: tab.helperPid,
    conversationKey,
    connectorBound: connectorBound === true,
    tabId: tab.id,
    stopRequested,
  };
}

function completeSteeringHandoff(host, handoff) {
  const tab = host?.turnTabs?.get(handoff.tabId);
  if (!tab || tab.traceId !== handoff.traceId || tab.helperPid !== handoff.helperPid) {
    throw new Error(`Browser steering handoff lost ownership of ${handoff.traceId}`);
  }
  if (tab.conversationKey !== handoff.conversationKey) {
    throw new Error(`Browser steering handoff changed conversation identity for ${handoff.traceId}`);
  }
  tab.status = "ready";
  tab.loading = false;
  tab.message = "Ready for Codex steering";
  tab.connectorBound = tab.connectorBound === true || handoff.connectorBound === true;
  tab.lastHeartbeatAt = Date.now();
  if (!tab.view.webContents.isDestroyed()) tab.view.webContents.setBackgroundThrottling(true);
  host.syncPowerSaveBlocker?.();
  host.publishState?.(host.snapshot());
  host.writeDescriptor?.();
  return { retained: true, stopRequested: handoff.stopRequested === true };
}

module.exports = { completeSteeringHandoff, requestSteeringHandoff };
