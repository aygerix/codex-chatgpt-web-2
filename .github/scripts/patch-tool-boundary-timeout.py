from pathlib import Path

progress = Path('src/adapters/chatgpt-web/turn-progress.ts')
s = progress.read_text()
old = '''/** Allows one bounded DOM probe plus cross-process delivery before failing the causal barrier. */
export const CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS = 10_000;
'''
new = '''/**
 * Causal barrier timeout for the browser to acknowledge a pre-tool answer boundary.
 *
 * The browser worker may legitimately consume up to three 5s DOM observation windows while
 * recovering the exact launcher-owned page (initial probe plus two same-page rebinds). The barrier
 * must outlive that bounded recovery envelope or it can kill a healthy accepted turn before the
 * worker has exhausted its own recovery policy. Keep additional headroom for the helper-process
 * progress frame, rebind handshake, and acknowledgement round-trip.
 */
export const CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS = 30_000;
'''
if old not in s:
    raise SystemExit('tool-boundary timeout declaration not found')
progress.write_text(s.replace(old, new, 1))

# Contract regression: the causal-barrier deadline must exceed the browser's entire bounded DOM
# recovery envelope rather than racing it.
test = Path('tests/turn-progress.test.ts')
if not test.exists():
    test.write_text('')
t = test.read_text()
marker = 'tool-boundary observation timeout covers the bounded browser recovery envelope'
if marker not in t:
    t += '''\nimport { expect, test } from "bun:test";\nimport { CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS } from "../src/adapters/chatgpt-web/turn-progress";\nimport { CHATGPT_BROWSER_OBSERVATION_PROBE_TIMEOUT_MS, MAX_CHATGPT_BROWSER_PAGE_REBINDS } from "../src/adapters/chatgpt-web/browser-worker";\n\ntest("tool-boundary observation timeout covers the bounded browser recovery envelope", () => {\n  const maximumProbeBudget = CHATGPT_BROWSER_OBSERVATION_PROBE_TIMEOUT_MS * (MAX_CHATGPT_BROWSER_PAGE_REBINDS + 1);\n  expect(maximumProbeBudget).toBe(15_000);\n  expect(CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS).toBeGreaterThan(maximumProbeBudget);\n  expect(CHATGPT_TOOL_BOUNDARY_OBSERVATION_TIMEOUT_MS).toBe(30_000);\n});\n'''
    test.write_text(t)
