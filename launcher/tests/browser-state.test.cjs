const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS,
  CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT,
} = require("../electron/browser-state.cjs");

test("history-limit CSS hides only the exact modal and does not force body scrolling", () => {
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS, /modal-conversation-history-rate-limit/);
  assert.doesNotMatch(CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS, /body\s*:/);
  assert.doesNotMatch(CONVERSATION_HISTORY_RATE_LIMIT_MODAL_CSS, /overflow:\s*auto/i);
});

test("history-limit recovery releases modal interaction locks without defeating other dialogs", () => {
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, /data-scroll-locked/);
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, /removeAttribute\("inert"\)/);
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, /anotherDialogIsOpen/);
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, /aria-label=\"Close\"/);
  assert.match(CONVERSATION_HISTORY_RATE_LIMIT_RECOVERY_SCRIPT, /KeyboardEvent\("keydown"/);
});
