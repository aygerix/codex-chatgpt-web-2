
import { expect, test } from "bun:test";
import { CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS } from "../src/adapters/chatgpt-web/turn-progress";
import { CHATGPT_BROWSER_OBSERVATION_PROBE_TIMEOUT_MS, MAX_CHATGPT_BROWSER_PAGE_REBINDS } from "../src/adapters/chatgpt-web/browser-worker";

test("tool-boundary observation timeout covers the bounded browser recovery envelope", () => {
  const maximumProbeBudget = CHATGPT_BROWSER_OBSERVATION_PROBE_TIMEOUT_MS * (MAX_CHATGPT_BROWSER_PAGE_REBINDS + 1);
  expect(maximumProbeBudget).toBe(15_000);
  expect(CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS).toBeGreaterThan(maximumProbeBudget);
  expect(CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS).toBe(30_000);
});
