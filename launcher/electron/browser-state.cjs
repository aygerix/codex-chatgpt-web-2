const CHATGPT_ORIGIN = "https://chatgpt.com";
const CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS = `
  #modal-conversation-history-rate-limit,
  [data-testid="modal-conversation-history-rate-limit"] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
  }
`;

const CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT = String.raw`
(() => {
  const stateKey = "__CODEX_WEB_HISTORY_RATE_LIMIT_RECOVERY_V1__";
  const existing = globalThis[stateKey];
  if (existing && typeof existing.recover === "function") {
    existing.recover();
    return true;
  }

  const modalSelector = [
    "#modal-conversation-history-rate-limit",
    '[data-testid="modal-conversation-history-rate-limit"]',
  ].join(", ");
  const attemptedDismiss = new WeakSet();

  const rendered = (element) => {
    if (!(element instanceof HTMLElement) || !element.isConnected) return false;
    const style = getComputedStyle(element);
    return style.display !== "none"
      && style.visibility !== "hidden"
      && style.opacity !== "0";
  };

  const topLevelPortal = (element) => {
    let current = element;
    while (current.parentElement && current.parentElement !== document.body) {
      current = current.parentElement;
    }
    return current;
  };

  const anotherDialogIsOpen = (historyDialog) => (
    [...document.querySelectorAll('[role="dialog"]')].some(candidate => (
      candidate !== historyDialog
      && !historyDialog.contains(candidate)
      && rendered(candidate)
    ))
  );

  const restoreBackgroundInteraction = (historyDialog, hiddenPortal) => {
    if (anotherDialogIsOpen(historyDialog)) return;

    const body = document.body;
    const html = document.documentElement;
    if (body) body.removeAttribute("data-scroll-locked");

    for (const element of [html, body]) {
      if (!element) continue;
      const overflow = element.style.getPropertyValue("overflow").trim().toLowerCase();
      if (overflow === "hidden" || overflow === "clip") {
        element.style.removeProperty("overflow");
      }
      if (element.style.getPropertyValue("pointer-events").trim().toLowerCase() === "none") {
        element.style.removeProperty("pointer-events");
      }
      if (element.style.getPropertyValue("touch-action").trim().toLowerCase() === "none") {
        element.style.removeProperty("touch-action");
      }
    }

    if (!body) return;
    for (const child of [...body.children]) {
      if (child === hiddenPortal) continue;
      if (child.hasAttribute("inert")) child.removeAttribute("inert");
    }
  };

  const recover = () => {
    const modal = document.querySelector(modalSelector);
    if (!(modal instanceof HTMLElement)) return false;

    const historyDialog = modal.closest('[role="dialog"]') || modal;
    if (!attemptedDismiss.has(historyDialog)) {
      attemptedDismiss.add(historyDialog);
      const close = historyDialog.querySelector([
        '[data-testid="modal-close-button"]',
        'button[data-testid="close-button"]',
        'button[aria-label="Close"]',
        'button[aria-label="Dismiss"]',
      ].join(", "));
      if (close instanceof HTMLElement) {
        close.click();
      } else {
        const escape = () => new KeyboardEvent("keydown", {
          key: "Escape",
          code: "Escape",
          bubbles: true,
          cancelable: true,
        });
        historyDialog.dispatchEvent(escape());
        document.dispatchEvent(escape());
      }
      queueMicrotask(recover);
      return true;
    }

    // Some history-limit dialogs are intentionally non-dismissible. In that case hide only the
    // portal that owns this exact dialog, then undo the modal library's interaction locks. Do not
    // unlock the background while any other visible dialog is open.
    const portal = topLevelPortal(historyDialog);
    if (portal instanceof HTMLElement) {
      portal.style.setProperty("display", "none", "important");
      portal.style.setProperty("visibility", "hidden", "important");
      portal.style.setProperty("pointer-events", "none", "important");
    } else {
      historyDialog.style.setProperty("display", "none", "important");
      historyDialog.style.setProperty("visibility", "hidden", "important");
      historyDialog.style.setProperty("pointer-events", "none", "important");
    }
    restoreBackgroundInteraction(historyDialog, portal);
    return true;
  };

  const observer = new MutationObserver(recover);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "data-scroll-locked", "inert", "style"],
  });
  globalThis[stateKey] = { observer, recover };
  recover();
  return true;
})()
`;

const chatGptUiFilterKeys = new WeakMap();

async function applyChatGptUiFilters(contents) {
  if (!contents || contents.isDestroyed()) return;
  let url;
  try {
    url = new URL(contents.getURL());
  } catch {
    return;
  }
  if (url.origin !== CHATGPT_ORIGIN) return;

  const previousKey = chatGptUiFilterKeys.get(contents);
  if (previousKey) {
    await contents.removeInsertedCSS(previousKey).catch(() => {});
    chatGptUiFilterKeys.delete(contents);
  }
  const key = await contents.insertCSS(CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS).catch(() => null);
  if (key) chatGptUiFilterKeys.set(contents, key);
  if (typeof contents.executeJavaScript === "function") {
    await contents.executeJavaScript(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, true).catch(() => {});
  }
}

function installChatGptUiFilters() {
  let electron;
  try {
    electron = require("electron");
  } catch {
    return;
  }
  const app = electron?.app;
  if (!app || typeof app.on !== "function") return;

  app.on("web-contents-created", (_event, contents) => {
    const apply = () => { void applyChatGptUiFilters(contents); };
    contents.on("did-finish-load", apply);
    contents.once("destroyed", () => chatGptUiFilterKeys.delete(contents));
    apply();
  });
}

installChatGptUiFilters();

function browserViewVisible(requestedVisible, surfaceActive, boundsReady = true) {
  return requestedVisible === true && surfaceActive === true && boundsReady === true;
}

function scaleBrowserBounds(bounds, zoomFactor = 1) {
  if (!Number.isFinite(zoomFactor) || zoomFactor <= 0) {
    throw new Error("Renderer zoom factor must be positive and finite");
  }
  return {
    x: bounds.x * zoomFactor,
    y: bounds.y * zoomFactor,
    width: bounds.width * zoomFactor,
    height: bounds.height * zoomFactor,
  };
}

function shellZoomActionForInput(input, platform = process.platform) {
  if (input?.type !== "keyDown" || input.alt === true) return null;
  const primaryModifier = platform === "darwin" ? input.meta === true : input.control === true;
  if (!primaryModifier) return null;
  if (input.key === "+" || input.key === "=") return "in";
  if (input.key === "-" || input.key === "_") return "out";
  if (input.key === "0") return "reset";
  return null;
}

function constrainBrowserBounds(bounds, contentSize) {
  const contentWidth = Math.max(1, Math.round(contentSize?.width || 0));
  const contentHeight = Math.max(1, Math.round(contentSize?.height || 0));
  const x = Math.min(contentWidth - 1, Math.max(0, Math.round(bounds.x)));
  const y = Math.min(contentHeight - 1, Math.max(0, Math.round(bounds.y)));
  return {
    x,
    y,
    width: Math.min(contentWidth - x, Math.max(1, Math.round(bounds.width))),
    height: Math.min(contentHeight - y, Math.max(1, Math.round(bounds.height))),
  };
}

function readBrowserNavigationState(contents, fallback) {
  if (!contents || contents.isDestroyed()) return { ...fallback };
  const history = contents.navigationHistory;
  return {
    ...fallback,
    url: contents.getURL() || fallback.url,
    title: contents.getTitle() || fallback.title || "ChatGPT",
    loading: contents.isLoading(),
    canGoBack: history.canGoBack(),
    canGoForward: history.canGoForward(),
  };
}

function navigateBrowser(contents, action) {
  const history = contents.navigationHistory;
  if (action === "back") {
    if (history.canGoBack()) history.goBack();
  } else if (action === "forward") {
    if (history.canGoForward()) history.goForward();
  } else if (action === "reload") {
    contents.reload();
  } else {
    throw new Error(`Unknown browser navigation action: ${action}`);
  }
}

module.exports = {
  CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS,
  CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT,
  browserViewVisible,
  constrainBrowserBounds,
  navigateBrowser,
  readBrowserNavigationState,
  scaleBrowserBounds,
  shellZoomActionForInput,
};