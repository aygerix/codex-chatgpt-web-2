from pathlib import Path

p = Path('src/adapters/chatgpt-web/browser-worker.ts')
s = p.read_text()
old = '''  private async waitForSteeredAssistantTurn(
    page: Page,
    knownResponseIdentities: ReadonlySet<string>,
    deadline: number | undefined,
    signal?: AbortSignal,
  ): Promise<{
    binding: ChatGptAssistantTurnBinding;
    baseline: ChatGptSubmissionBaseline;
    state: ChatGptSubmissionDomState;
  }> {
    const responseDeadline = Math.min(
      deadline ?? Number.POSITIVE_INFINITY,
      Date.now() + CHATGPT_RESPONSE_DOM_GRACE_MS,
    );
    for (;;) {
      if (signal?.aborted) throw new DOMException("ChatGPT web turn aborted", "AbortError");
      if (page.isClosed()) throw chatGptBrowserTabClosedError();
      if (deadline !== undefined && Date.now() >= deadline) throw new Error("ChatGPT web turn timed out");
      if (Date.now() >= responseDeadline) {
        throw new Error("ChatGPT accepted Codex steering but did not expose its steered assistant turn in the DOM");
      }
      const state = await this.submissionDomState(page, undefined, signal);
      const newResponses = state.responseIdentities.filter(identity => !knownResponseIdentities.has(identity));
      if (newResponses.length > 0) {
        const identity = newResponses.at(-1)!;
        const initialResponseTurnIdentities = state.responseIdentities.filter(candidate => candidate !== identity);
        const baseline: ChatGptSubmissionBaseline = {
          userTurns: page.locator(CHATGPT_USER_TURN_SELECTOR),
          responseTurns: page.locator(CHATGPT_ASSISTANT_TURN_SELECTOR),
          initialUserTurnCount: Math.max(0, state.userTurnCount - 1),
          initialResponseTurnCount: Math.max(0, state.assistantTurnCount - 1),
          initialUserTurnIdentities: state.userIdentities.slice(0, -1),
          initialResponseTurnIdentities,
          domCache: {},
        };
        return {
          state,
          baseline,
          binding: {
            identity,
            locator: page.locator(`[data-testid=${JSON.stringify(identity)}]`),
            acceptedUserTurnIdentities: state.userIdentities,
          },
        };
      }
      await this.waitForTurnDomMutation(page, 50);
    }
  }
'''
new = '''  private async waitForSteeredAssistantTurn(
    page: Page,
    revision: number,
    previousUserTurnCount: number,
    knownResponseIdentities: ReadonlySet<string>,
    deadline: number | undefined,
    signal?: AbortSignal,
  ): Promise<{
    binding: ChatGptAssistantTurnBinding;
    baseline: ChatGptSubmissionBaseline;
    state: ChatGptSubmissionDomState;
  }> {
    const responseDeadline = Math.min(
      deadline ?? Number.POSITIVE_INFINITY,
      Date.now() + CHATGPT_RESPONSE_DOM_GRACE_MS,
    );
    const markerAttribute = "data-codex-web-gpt-steer-assistant-revision";
    for (;;) {
      if (signal?.aborted) throw new DOMException("ChatGPT web turn aborted", "AbortError");
      if (page.isClosed()) throw chatGptBrowserTabClosedError();
      if (deadline !== undefined && Date.now() >= deadline) throw new Error("ChatGPT web turn timed out");
      if (Date.now() >= responseDeadline) {
        throw new Error("ChatGPT accepted Codex steering but did not expose its steered assistant turn in the DOM");
      }

      // Prefer ChatGPT's stable conversation-turn identity when the product exposes it immediately.
      // Lower-effort modes can visibly stream a new assistant response before assigning that stable
      // data-testid. Waiting for the id in that case buffered the entire post-steer response until
      // completion even though the live DOM already contained the answer. Fall back to the semantic
      // assistant node after the newest post-steer user turn and tag its nearest turn/article root
      // with our own revision-scoped locator. If ChatGPT later replaces that provisional root, the
      // ordinary reconciliation path below upgrades the binding to the eventual stable identity.
      const stableState = await this.submissionDomState(page, undefined, signal);
      const newResponses = stableState.responseIdentities.filter(identity => !knownResponseIdentities.has(identity));
      if (newResponses.length > 0) {
        const identity = newResponses.at(-1)!;
        const initialResponseTurnIdentities = stableState.responseIdentities.filter(candidate => candidate !== identity);
        const baseline: ChatGptSubmissionBaseline = {
          userTurns: page.locator(CHATGPT_USER_TURN_SELECTOR),
          responseTurns: page.locator(CHATGPT_ASSISTANT_TURN_SELECTOR),
          initialUserTurnCount: Math.max(0, stableState.userTurnCount - 1),
          initialResponseTurnCount: Math.max(0, stableState.assistantTurnCount - 1),
          initialUserTurnIdentities: stableState.userIdentities.slice(0, -1),
          initialResponseTurnIdentities,
          domCache: {},
        };
        return {
          state: stableState,
          baseline,
          binding: {
            identity,
            locator: page.locator(`[data-testid=${JSON.stringify(identity)}]`),
            acceptedUserTurnIdentities: stableState.userIdentities,
          },
        };
      }

      const provisional = await withBrowserTurnAbort(
        withChatGptBrowserObservationTimeout(page.evaluate(options => {
          const rootsFor = (role: "user" | "assistant"): HTMLElement[] => {
            const candidates = [
              ...document.querySelectorAll<HTMLElement>(`[data-message-author-role="${role}"]`),
              ...document.querySelectorAll<HTMLElement>(`[data-turn="${role}"]`),
            ];
            const seen = new Set<HTMLElement>();
            const roots: HTMLElement[] = [];
            for (const candidate of candidates) {
              const root = candidate.closest<HTMLElement>('[data-testid^="conversation-turn-"]')
                ?? candidate.closest<HTMLElement>("article")
                ?? candidate;
              if (seen.has(root)) continue;
              seen.add(root);
              roots.push(root);
            }
            roots.sort((left, right) => {
              if (left === right) return 0;
              return left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
            });
            return roots;
          };
          const stableIdentities = (roots: readonly HTMLElement[]): string[] => roots
            .map(root => root.getAttribute("data-testid"))
            .filter((value): value is string => typeof value === "string" && value.startsWith("conversation-turn-"));
          const visible = (element: Element): boolean => {
            const candidate = element as HTMLElement;
            const style = getComputedStyle(candidate);
            const bounds = candidate.getBoundingClientRect();
            return candidate.isConnected
              && style.visibility !== "hidden"
              && (bounds.width > 0 || bounds.height > 0);
          };

          const users = rootsFor("user");
          if (users.length <= options.previousUserTurnCount) return null;
          const steerUser = users.at(-1)!;
          const assistants = rootsFor("assistant");
          const following = assistants.filter(candidate => Boolean(
            steerUser.compareDocumentPosition(candidate) & Node.DOCUMENT_POSITION_FOLLOWING,
          ));
          const assistant = following.at(-1);
          if (!assistant) return null;
          assistant.setAttribute(options.markerAttribute, String(options.revision));
          const identity = assistant.getAttribute("data-testid");
          return {
            userTurnCount: users.length,
            assistantTurnCount: assistants.length,
            visibleStopButtonCount: [...document.querySelectorAll(options.stopButtonSelector)].filter(visible).length,
            userIdentities: stableIdentities(users),
            responseIdentities: stableIdentities(assistants),
            identity: typeof identity === "string" && identity.startsWith("conversation-turn-") ? identity : null,
          };
        }, {
          revision,
          previousUserTurnCount,
          markerAttribute,
          stopButtonSelector: CHATGPT_STOP_BUTTON_SELECTOR,
        })),
        signal,
      );
      if (provisional) {
        const state: ChatGptSubmissionDomState = {
          userTurnCount: provisional.userTurnCount,
          assistantTurnCount: provisional.assistantTurnCount,
          visibleStopButtonCount: provisional.visibleStopButtonCount,
          userIdentities: provisional.userIdentities,
          responseIdentities: provisional.responseIdentities,
        };
        const stableIdentity = provisional.identity ?? undefined;
        const identity = stableIdentity ?? `codex-steer-${revision}`;
        const initialResponseTurnIdentities = stableIdentity
          ? state.responseIdentities.filter(candidate => candidate !== stableIdentity)
          : state.responseIdentities;
        const baseline: ChatGptSubmissionBaseline = {
          userTurns: page.locator(CHATGPT_USER_TURN_SELECTOR),
          responseTurns: page.locator(CHATGPT_ASSISTANT_TURN_SELECTOR),
          initialUserTurnCount: Math.max(0, state.userTurnCount - 1),
          initialResponseTurnCount: Math.max(0, state.assistantTurnCount - 1),
          initialUserTurnIdentities: state.userIdentities.slice(0, -1),
          initialResponseTurnIdentities,
          domCache: {},
        };
        return {
          state,
          baseline,
          binding: {
            identity,
            locator: page.locator(`[${markerAttribute}=${JSON.stringify(String(revision))}]`),
            acceptedUserTurnIdentities: state.userIdentities,
          },
        };
      }
      await this.waitForTurnDomMutation(page, 50);
    }
  }
'''
if old not in s:
    raise SystemExit('steered assistant wait function not found')
s = s.replace(old, new, 1)

old = '''    const identity = chatGptReboundTurnIdentity(
      baseline.initialResponseTurnIdentities,
      binding.identity,
      state.responseIdentities,
    );
'''
new = '''    const identity = binding.identity.startsWith("codex-steer-")
      ? chatGptNewTurnIdentity(
        baseline.initialResponseTurnIdentities,
        state.responseIdentities,
      )
      : chatGptReboundTurnIdentity(
        baseline.initialResponseTurnIdentities,
        binding.identity,
        state.responseIdentities,
      );
'''
if old not in s:
    raise SystemExit('assistant rebound block not found')
s = s.replace(old, new, 1)

old = '''        const steered = await this.waitForSteeredAssistantTurn(
          page,
          knownResponseIdentities,
          deadline,
          turn.abortSignal,
        );
'''
new = '''        const previousUserTurnCount = Math.max(
          submissionBaseline.initialUserTurnCount + 1,
          responseTurn.acceptedUserTurnIdentities.length,
        );
        const steered = await this.waitForSteeredAssistantTurn(
          page,
          revision,
          previousUserTurnCount,
          knownResponseIdentities,
          deadline,
          turn.abortSignal,
        );
'''
if old not in s:
    raise SystemExit('applyCodexSteer call not found')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('tests/chatgpt-steering-lifecycle.test.ts')
s = p.read_text()
addition = r'''

test("lower-effort steering can bind a semantic assistant before ChatGPT assigns a stable turn id", () => {
  const source = readFileSync("src/adapters/chatgpt-web/browser-worker.ts", "utf8");
  expect(source).toContain('data-codex-web-gpt-steer-assistant-revision');
  expect(source).toContain('`[data-message-author-role="${role}"]`');
  expect(source).toContain('candidate.closest<HTMLElement>("article")');
  expect(source).toContain('const identity = stableIdentity ?? `codex-steer-${revision}`');
  expect(source).toContain('binding.identity.startsWith("codex-steer-")');
  expect(source).toContain('revision,\n          previousUserTurnCount,\n          knownResponseIdentities');
});
'''
if 'lower-effort steering can bind a semantic assistant' not in s:
    s += addition
p.write_text(s)
