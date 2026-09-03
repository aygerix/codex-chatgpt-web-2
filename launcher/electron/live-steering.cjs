const CHATGPT_COMPOSER_SELECTOR = [
  '[data-testid="prompt-textarea"]',
  '#prompt-textarea',
  '[contenteditable="true"][data-lexical-editor="true"]',
].join(", ");
const CHATGPT_USER_TURN_SELECTOR = [
  '[data-testid^="conversation-turn-"][data-turn="user"]',
  '[data-testid^="conversation-turn-"][data-message-author-role="user"]',
  '[data-testid^="conversation-turn-"]:has([data-message-author-role="user"])',
].join(", ");
const MAX_STEER_TEXT_CHARS = 200_000;

function validateLiveSteerInput(input) {
  if (!input || typeof input !== "object") throw new Error("steer input is invalid");
  if (!/^[A-Za-z0-9_-]{6,128}$/.test(input.traceId || "")) throw new Error("traceId is invalid");
  if (!Number.isSafeInteger(input.logId) || input.logId < 1) throw new Error("steer logId is invalid");
  if (typeof input.text !== "string" || !input.text.trim()) throw new Error("steer text is empty");
  if (input.text.length > MAX_STEER_TEXT_CHARS) throw new Error("steer text is too large");
  return input;
}

function liveSteerScript(text, revision) {
  return `(async () => {
    const composerSelector = ${JSON.stringify(CHATGPT_COMPOSER_SELECTOR)};
    const userTurnSelector = ${JSON.stringify(CHATGPT_USER_TURN_SELECTOR)};
    const text = ${JSON.stringify(text)};
    const revision = ${JSON.stringify(revision)};
    const visible = (element) => {
      const style = getComputedStyle(element);
      const bounds = element.getBoundingClientRect();
      return element.isConnected
        && bounds.width > 0
        && bounds.height > 0
        && style.display !== "none"
        && style.visibility !== "hidden";
    };
    const composers = [...document.querySelectorAll(composerSelector)].filter(visible);
    if (composers.length !== 1) {
      throw new Error("ChatGPT steer requires exactly one visible composer");
    }
    const composer = composers[0];
    const clone = composer.cloneNode(true);
    clone.querySelectorAll(
      '[data-id^="plugin:"][data-keyword], [data-inline-selection-pill-cursor-target]'
    ).forEach(part => part.remove());
    const draft = (clone.innerText ?? clone.textContent ?? "").trim();
    if (draft) throw new Error("ChatGPT composer already contains an unsent draft");

    const initialUsers = document.querySelectorAll(userTurnSelector).length;
    composer.focus();
    if (document.activeElement !== composer) throw new Error("ChatGPT steer could not focus the composer");
    const selection = getSelection();
    if (!selection) throw new Error("ChatGPT steer could not access the composer selection");
    const range = document.createRange();
    range.selectNodeContents(composer);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
    if (!document.execCommand("insertText", false, text)) {
      throw new Error("ChatGPT steer composer rejected text insertion");
    }

    const deadline = Date.now() + 10000;
    let send;
    while (Date.now() < deadline) {
      const form = composer.closest("form");
      send = form?.querySelector('[data-testid="send-button"]');
      if (send && visible(send) && !send.disabled && send.getAttribute("aria-disabled") !== "true") break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    if (!send) throw new Error("ChatGPT steer did not expose an enabled send button");
    send.click();

    while (Date.now() < deadline) {
      const userCount = document.querySelectorAll(userTurnSelector).length;
      const currentClone = composer.cloneNode(true);
      currentClone.querySelectorAll(
        '[data-id^="plugin:"][data-keyword], [data-inline-selection-pill-cursor-target]'
      ).forEach(part => part.remove());
      const remaining = (currentClone.innerText ?? currentClone.textContent ?? "").trim();
      if (userCount > initialUsers || remaining.length === 0) {
        globalThis.__CODEX_WEB_GPT_STEER_REVISION__ = revision;
        document.documentElement.dataset.codexWebGptSteerRevision = String(revision);
        return { accepted: true, userTurnObserved: userCount > initialUsers };
      }
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error("ChatGPT steer send was activated but acceptance was not observed");
  })()`;
}

async function steerRunningTurn(host, rawInput) {
  const input = validateLiveSteerInput(rawInput);
  const tab = [...host.turnTabs.values()].find(candidate => candidate.traceId === input.traceId);
  if (!tab) throw new Error(`Browser turn ownership mismatch: no browser tab owns ${input.traceId}`);
  if (tab.status !== "running") throw new Error(`Browser turn ${input.traceId} is no longer running`);
  if (tab.view.webContents.isDestroyed()) throw new Error(`Browser turn ${input.traceId} page is closed`);
  const previousLogId = Number.isSafeInteger(tab.lastSteerLogId) ? tab.lastSteerLogId : 0;
  const previousRevision = Number.isSafeInteger(tab.steerRevision) ? tab.steerRevision : 0;
  if (input.logId <= previousLogId) {
    return { revision: previousRevision, duplicate: true };
  }
  const revision = previousRevision + 1;
  const result = await tab.view.webContents.executeJavaScript(
    liveSteerScript(input.text, revision),
    true,
  );
  if (!result || result.accepted !== true) throw new Error("ChatGPT steer did not return acceptance evidence");
  tab.lastSteerLogId = input.logId;
  tab.steerRevision = revision;
  tab.lastHeartbeatAt = Date.now();
  host.logger.info("browser.turn_steered", {
    traceId: input.traceId,
    revision,
    textChars: input.text.length,
    userTurnObserved: result.userTurnObserved === true,
  });
  host.publishState?.(host.snapshot());
  return { revision, duplicate: false };
}

module.exports = {
  CHATGPT_COMPOSER_SELECTOR,
  CHATGPT_USER_TURN_SELECTOR,
  MAX_STEER_TEXT_CHARS,
  liveSteerScript,
  steerRunningTurn,
  validateLiveSteerInput,
};
