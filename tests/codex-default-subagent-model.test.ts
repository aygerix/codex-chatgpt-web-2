import { expect, test } from "bun:test";
import { findAgentDefaultSubagentModelAssignment } from "../src/codex-integration-document";

test("reads the configured default Web subagent model from the agents table", () => {
  expect(findAgentDefaultSubagentModelAssignment([
    "model = \"gpt-5.6-sol\"",
    "[agents]",
    "default_subagent_model = \"chatgpt-web/extra-high\"",
    "max_depth = 2",
  ])).toMatchObject({ present: true, value: "chatgpt-web/extra-high" });
});

test("does not invent a default child model when agents table omits it", () => {
  expect(findAgentDefaultSubagentModelAssignment(["[agents]", "max_depth = 2"])).toEqual({ present: false });
});
