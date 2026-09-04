from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


source_path = Path("src/adapters/chatgpt-web/browser-worker.ts")
source = source_path.read_text()

start = source.index("  private async waitForSubmissionAccepted(\n")
end = source.index("  private async submissionDomState(\n", start)
new_wait = '''  private async waitForSubmissionAccepted(
    page: Page,
    baseline: ChatGptSubmissionBaseline,
    signal?: AbortSignal,
    externalProgress?: ChatGptTurnProgressReader,
    initialToolBatchRevision = externalProgress?.snapshot().lastToolBatchRevision ?? 0,
    completionTracker?: ChatGptCompletionTracker,
    recoverObservation?: (
      baseline: ChatGptSubmissionBaseline,
      attempt: number,
      cause: ChatGptBrowserObservationTimeoutError,
    ) => Promise<Page>,
  ): Promise<ChatGptSubmissionEvidence> {
    if (signal?.aborted) throw new DOMException("ChatGPT web turn aborted", "AbortError");
    let activePage = page;
    let consecutiveObservationTimeouts = 0;
    const observeDom = async (): Promise<
      | { kind: "dom"; value: ChatGptSubmissionEvidence | undefined }
      | { kind: "dom_timeout"; error: ChatGptBrowserObservationTimeoutError }
    > => {
      try {
        return { kind: "dom", value: await this.currentSubmissionEvidence(activePage, baseline, signal) };
      } catch (error) {
        if (!(error instanceof ChatGptBrowserObservationTimeoutError)) throw error;
        return { kind: "dom_timeout", error };
      }
    };
    for (;;) {
      if (signal?.aborted) throw new DOMException("ChatGPT web turn aborted", "AbortError");
      const progress = externalProgress?.snapshot();
      // A new broker tool batch is semantic proof that ChatGPT accepted this exact prompt. Check it
      // before touching the DOM again: a renderer probe that is already wedged must never outrun
      // stronger cross-process acceptance evidence and turn a live tool call into an ambiguous send.
      if (progress && progress.lastToolBatchRevision > initialToolBatchRevision) return "mcp_tool_call";
      if (progress
        && externalProgress
        && completionTracker?.needsToolBatchObservation(progress.lastToolBatchRevision)) {
        const boundaryText = await this.currentSubmissionAnswerText(activePage, baseline, signal);
        completionTracker.observeToolBatch(progress.lastToolBatchRevision, boundaryText);
        await externalProgress.acknowledgeToolBatch(progress.lastToolBatchRevision);
      }
      await throwIfChatGptSessionFailureAlert(activePage);
      await throwIfChatGptTerminalErrorAlert(baseline.responseTurns.last());
      let observed:
        | { kind: "dom"; value: ChatGptSubmissionEvidence | undefined }
        | { kind: "dom_timeout"; error: ChatGptBrowserObservationTimeoutError }
        | { kind: "external" };
      if (externalProgress) {
        const progressWaitAbort = new AbortController();
        const progressSignal = signal
          ? AbortSignal.any([progressWaitAbort.signal, signal])
          : progressWaitAbort.signal;
        try {
          observed = await withBrowserTurnAbort(Promise.race([
            observeDom(),
            externalProgress.waitForChange(progress?.revision ?? 0, progressSignal)
              .then(() => ({ kind: "external" as const })),
          ]), signal);
        } finally {
          progressWaitAbort.abort();
        }
      } else {
        observed = await observeDom();
      }
      if (observed.kind === "external") continue;
      if (observed.kind === "dom_timeout") {
        // The timeout only says this CDP connection failed to answer one bounded observation. It
        // says nothing about whether the already-activated Send was accepted. Re-check broker
        // progress first because the tool call may have landed in the small race between the DOM
        // timeout and this handler.
        const latestProgress = externalProgress?.snapshot();
        if (latestProgress && latestProgress.lastToolBatchRevision > initialToolBatchRevision) {
          return "mcp_tool_call";
        }
        consecutiveObservationTimeouts += 1;
        if (!recoverObservation) throw observed.error;
        if (consecutiveObservationTimeouts > MAX_CHATGPT_BROWSER_PAGE_REBINDS) {
          throw new Error(
            `ChatGPT browser DOM remained unresponsive while proving submission acceptance after ${MAX_CHATGPT_BROWSER_PAGE_REBINDS} same-page rebinds`,
            { cause: observed.error },
          );
        }
        // Rebind the same launcher-owned tab. Closing the stale CDP connection is important: the
        // timed-out page.evaluate may still be pending underneath the timeout race, so issuing more
        // reads on that connection can pile up behind a renderer that is already wedged.
        activePage = await recoverObservation(
          baseline,
          consecutiveObservationTimeouts,
          observed.error,
        );
        continue;
      }
      consecutiveObservationTimeouts = 0;
      if (observed.value) return observed.value;
      await this.waitForTurnDomOrExternalProgress(
        activePage,
        progress?.revision ?? 0,
        externalProgress,
        signal,
      );
    }
  }

'''
source = source[:start] + new_wait + source[end:]

source = replace_once(
    source,
    '''    abortSignal?: AbortSignal,\n    externalProgress?: ChatGptTurnProgressReader,\n    submissionLifecycle?: Pick<BrowserTurn, "onSendActivated" | "onSubmitted">,\n    completionTracker?: ChatGptCompletionTracker,\n  ): Promise<ChatGptSubmissionEvidence> {''',
    '''    abortSignal?: AbortSignal,\n    recoverObservation?: (\n      baseline: ChatGptSubmissionBaseline,\n      attempt: number,\n      cause: ChatGptBrowserObservationTimeoutError,\n    ) => Promise<Page>,\n    externalProgress?: ChatGptTurnProgressReader,\n    submissionLifecycle?: Pick<BrowserTurn, "onSendActivated" | "onSubmitted">,\n    completionTracker?: ChatGptCompletionTracker,\n  ): Promise<ChatGptSubmissionEvidence> {''',
    "sendAttachedPrompt signature",
)
source = replace_once(
    source,
    '''      initialToolBatchRevision,\n      completionTracker,\n    );''',
    '''      initialToolBatchRevision,\n      completionTracker,\n      recoverObservation,\n    );''',
    "sendAttachedPrompt acceptance call",
)

rebind_marker = '''        console.warn(\n          `[chatgpt-web] browser turn ${turn.traceId} rebound its existing launcher page after a stalled DOM probe`,\n        );\n      };\n      await diagnostics.capture(page, "browser-page-acquired");'''
rebind_replacement = '''        console.warn(\n          `[chatgpt-web] browser turn ${turn.traceId} rebound its existing launcher page after a stalled DOM probe`,\n        );\n      };\n      const recoverSubmissionObservation = async (\n        baseline: ChatGptSubmissionBaseline,\n        attempt: number,\n        cause: ChatGptBrowserObservationTimeoutError,\n      ): Promise<Page> => {\n        await rebindLauncherPage(attempt, cause);\n        // Rebuild every page-bound locator and discard the old observer revision cache. The\n        // semantic baseline counts/identities stay intact because this is the same browser tab and\n        // the same already-activated submission, not a replay.\n        baseline.userTurns = page.locator(CHATGPT_USER_TURN_SELECTOR);\n        baseline.responseTurns = page.locator(CHATGPT_ASSISTANT_TURN_SELECTOR);\n        baseline.domCache = {};\n        await diagnostics.capture(page, "submission-page-rebound-after-observation-timeout");\n        return page;\n      };\n      await diagnostics.capture(page, "browser-page-acquired");'''
source = replace_once(source, rebind_marker, rebind_replacement, "submission rebind helper")

source = replace_once(
    source,
    '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\n            ),''',
    '''              checkpoint => diagnostics.capture(page, `multipart-${index + 1}-${checkpoint}`),\n              turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\n              recoverSubmissionObservation,\n            ),''',
    "multipart send recovery",
)
source = replace_once(
    source,
    '''          checkpoint => diagnostics.capture(page, checkpoint),\n          turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\n          turn.externalProgress,\n          turn,\n          completionTracker,\n        ),''',
    '''          checkpoint => diagnostics.capture(page, checkpoint),\n          turn.abortSignal ? AbortSignal.any([stageSignal, turn.abortSignal]) : stageSignal,\n          recoverSubmissionObservation,\n          turn.externalProgress,\n          turn,\n          completionTracker,\n        ),''',
    "final send recovery",
)

source_path.write_text(source)

test_path = Path("tests/browser-worker-contract.test.ts")
test_source = test_path.read_text()
insert_marker = '''});\n\ntest("conversation turn identity survives ChatGPT DOM virtualization", () => {'''
new_test = '''});\n\ntest("submission acceptance recovers a stalled DOM probe without losing authoritative tool progress", () => {\n  const workerSource = readFileSync(new URL("../src/adapters/chatgpt-web/browser-worker.ts", import.meta.url), "utf8");\n  const acceptance = workerSource.slice(\n    workerSource.indexOf("  private async waitForSubmissionAccepted("),\n    workerSource.indexOf("  private async submissionDomState("),\n  );\n  const toolAcceptance = acceptance.indexOf("progress.lastToolBatchRevision > initialToolBatchRevision");\n  const boundaryRead = acceptance.indexOf("this.currentSubmissionAnswerText(");\n  expect(toolAcceptance).toBeGreaterThan(-1);\n  expect(boundaryRead).toBeGreaterThan(toolAcceptance);\n  expect(acceptance).toContain('kind: "dom_timeout"');\n  expect(acceptance).toContain("error instanceof ChatGptBrowserObservationTimeoutError");\n  expect(acceptance).toContain("latestProgress.lastToolBatchRevision > initialToolBatchRevision");\n  expect(acceptance).toContain("consecutiveObservationTimeouts > MAX_CHATGPT_BROWSER_PAGE_REBINDS");\n  expect(acceptance).toContain("activePage = await recoverObservation(");\n  expect(acceptance).toContain("timed-out page.evaluate may still be pending");\n\n  const sendAttachedPrompt = workerSource.slice(\n    workerSource.indexOf("  private async sendAttachedPrompt("),\n    workerSource.indexOf("  private async waitForMultipartAcknowledgement("),\n  );\n  expect(sendAttachedPrompt).toContain("recoverObservation?: (");\n  expect(sendAttachedPrompt).toContain("recoverObservation,\\n    );");\n\n  const runBrowserTurn = workerSource.slice(workerSource.indexOf("  private async runBrowserTurn("));\n  const recoveryHelper = runBrowserTurn.slice(\n    runBrowserTurn.indexOf("const recoverSubmissionObservation = async ("),\n    runBrowserTurn.indexOf('await diagnostics.capture(page, "browser-page-acquired")'),\n  );\n  expect(recoveryHelper).toContain("await rebindLauncherPage(attempt, cause)");\n  expect(recoveryHelper).toContain("baseline.userTurns = page.locator(CHATGPT_USER_TURN_SELECTOR)");\n  expect(recoveryHelper).toContain("baseline.responseTurns = page.locator(CHATGPT_ASSISTANT_TURN_SELECTOR)");\n  expect(recoveryHelper).toContain("baseline.domCache = {}");\n  expect(runBrowserTurn.split("recoverSubmissionObservation,").length - 1).toBe(2);\n});\n\ntest("conversation turn identity survives ChatGPT DOM virtualization", () => {'''
test_source = replace_once(test_source, insert_marker, new_test, "submission race regression test")
test_path.write_text(test_source)

print("patched submission acceptance race and regression coverage")
