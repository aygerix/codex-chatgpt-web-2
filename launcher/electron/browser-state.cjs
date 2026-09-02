const CHATGPT_ORIGIN = "https://chatgpt.com";
const CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS = `
  #modal-conversation-history-rate-limit,
  [data-testid="modal-conversation-history-rate-limit"] {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
  }
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
  browserViewVisible,
  constrainBrowserBounds,
  navigateBrowser,
  readBrowserNavigationState,
  scaleBrowserBounds,
  shellZoomActionForInput,
};
