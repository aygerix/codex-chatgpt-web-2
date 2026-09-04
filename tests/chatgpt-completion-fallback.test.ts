import { expect, test } from "bun:test";
import {
  ChatGptCompletionTracker,
  ChatGptTurnDomHealthTracker,
  chatGptTurnIsComplete,
} from "../src/adapters/chatgpt-web/browser-worker";

test("completion accepts stable stopped answer when streaming status is retired without Copy action", () => {
  const state = {
    responsePresent: true, running: false, currentText: "done", currentHtml: "<p>done</p>",
    completionActionVisible: false, streamingStatusVisible: false,
  };
  expect(chatGptTurnIsComplete(state)).toBe(true);
  const tracker = new ChatGptCompletionTracker(2_000);
  expect(tracker.update(state, 1_000)).toBe(false);
  expect(tracker.update(state, 3_001)).toBe(true);
});

test("completion still waits when streaming status remains live and Copy action is absent", () => {
  const state = {
    responsePresent: true, running: false, currentText: "done", currentHtml: "<p>done</p>",
    completionActionVisible: false, streamingStatusVisible: true,
  };
  expect(chatGptTurnIsComplete(state)).toBe(false);
  const tracker = new ChatGptCompletionTracker(0);
  expect(tracker.update(state, 1_000)).toBe(false);
});

test("DOM health does not reject missing Copy action after streaming status retires", () => {
  const tracker = new ChatGptTurnDomHealthTracker(60_000, 10_000, 1_000);
  const retired = {
    responsePresent: true, running: false, currentText: "done",
    completionActionVisible: false, streamingStatusVisible: false,
  };
  expect(tracker.update(retired, 1_000)).toBeUndefined();
  expect(tracker.update(retired, 5_000)).toBeUndefined();

  const ambiguous = { ...retired, streamingStatusVisible: true };
  expect(tracker.update(ambiguous, 6_000)).toBeUndefined();
  expect(tracker.update(ambiguous, 7_001)).toContain("completed-turn action");
});
