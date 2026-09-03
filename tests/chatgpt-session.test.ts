import { expect, test } from "bun:test";
import {
  CHATGPT_COMPOSER_SELECTOR,
  CHATGPT_EFFORT_CONTROL_SELECTOR,
  CHATGPT_EFFORT_MENU_SELECTOR,
  CHATGPT_EFFORT_SLIDER_SELECTOR,
  CHATGPT_NEW_CHAT_URL,
  CHATGPT_REGULAR_CHAT_URL,
  detectChatGptAccountCapabilities,
} from "../src/chatgpt-session";

test("regular history-backed chats are the only surface", () => {
  expect(CHATGPT_NEW_CHAT_URL).toBe(CHATGPT_REGULAR_CHAT_URL);
  expect(CHATGPT_NEW_CHAT_URL).toBe("https://chatgpt.com/");
});

test("login keeps the established turn composer contract", () => {
  const turnSelectors = CHATGPT_COMPOSER_SELECTOR.split(",").map(selector => selector.trim());
  expect(turnSelectors).toContain('[data-testid="prompt-textarea"]');
  expect(turnSelectors).toContain("#prompt-textarea");
  expect(turnSelectors).toContain('[contenteditable="true"][data-lexical-editor="true"]');
  expect(turnSelectors).not.toContain('form [contenteditable="true"]');
  expect(turnSelectors).not.toContain("form textarea[placeholder]");
});

test("the effort selector identifies the model slider instead of any composer menu button", () => {
  expect(CHATGPT_EFFORT_CONTROL_SELECTOR).toContain('button[aria-haspopup="menu"][data-tone="neutral"]');
  expect(CHATGPT_EFFORT_CONTROL_SELECTOR).toContain('[data-testid="model-switcher-dropdown-button"]');
  expect(CHATGPT_EFFORT_CONTROL_SELECTOR).not.toBe('button[aria-haspopup="menu"]');
});

test("a complete authenticated composer with no effort selector is Luna-only", async () => {
  const effortButton = {
    last() { return this; },
    isVisible: async () => false,
  };
  const composerForm = {
    count: async () => 1,
    locator: () => effortButton,
  };
  const composer = {
    filter() { return this; },
    last() { return this; },
    count: async () => 1,
    isVisible: async () => true,
    locator: () => composerForm,
  };
  const page = {
    locator: () => composer,
    evaluate: async () => true,
  };

  await expect(detectChatGptAccountCapabilities(page as never, {
    selectorTimeoutMs: 100,
    stableAbsenceMs: 0,
  })).resolves.toEqual({ solAvailable: false, proAvailable: false });
});

test("a transient effort control does not turn a Luna-only account into Sol", async () => {
  let visibilityReads = 0;
  const effortButton = {
    last() { return this; },
    isVisible: async () => {
      visibilityReads += 1;
      return visibilityReads === 1;
    },
  };
  const composerForm = {
    count: async () => 1,
    locator: () => effortButton,
  };
  const composers = {
    filter() { return this; },
    last() { return this; },
    count: async () => 1,
    locator: () => composerForm,
  };
  const page = {
    locator: () => composers,
    evaluate: async () => true,
  };

  await expect(detectChatGptAccountCapabilities(page as never, {
    selectorTimeoutMs: 100,
    stableAbsenceMs: 0,
  })).resolves.toEqual({ solAvailable: false, proAvailable: false });
  expect(visibilityReads).toBe(2);
});

test("the new model rows cannot hide an authoritative five-step Pro effort slider", async () => {
  const effortButton = {
    last() { return this; },
    isVisible: async () => true,
    getAttribute: async () => "true",
  };
  const composerForm = {
    locator: () => effortButton,
  };
  const composers = {
    filter() { return this; },
    last() { return this; },
    locator: () => composerForm,
  };
  const efforts = {
    first() { return this; },
    waitFor: async () => {},
    count: async () => 2,
  };
  const menu = {
    last() { return this; },
    isVisible: async () => true,
    locator: () => efforts,
  };
  const slider = {
    filter() { return this; },
    last() { return this; },
    waitFor: async () => {},
    isVisible: async () => true,
    getAttribute: async (name: string) => ({
      "aria-valuemin": "0",
      "aria-valuemax": "4",
      "aria-valuenow": "3",
    })[name] ?? null,
  };
  const page = {
    locator: (selector: string) => {
      if (selector === CHATGPT_COMPOSER_SELECTOR) return composers;
      if (selector === CHATGPT_EFFORT_MENU_SELECTOR) return menu;
      if (selector === CHATGPT_EFFORT_SLIDER_SELECTOR) return slider;
      throw new Error(`Unexpected selector: ${selector}`);
    },
    keyboard: { press: async () => {} },
  };

  await expect(detectChatGptAccountCapabilities(page as never)).resolves.toEqual({
    solAvailable: true,
    proAvailable: true,
  });
});