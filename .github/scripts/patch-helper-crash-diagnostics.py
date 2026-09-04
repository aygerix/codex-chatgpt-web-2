from pathlib import Path

# Keep helper stderr alive through shutdown, report crash reasons, and trap otherwise opaque
# process-level failures before exiting.
p = Path('src/adapters/chatgpt-web/browser-helper-main.ts')
s = p.read_text()
old = '''let outputFailure: Error | undefined;\nconst handleOutputFailure = (error: Error): void => {\n  if (outputFailure) return;\n  outputFailure = error;\n  void requestShutdown();\n};\nconst protocolOutput = createProcessLineWriter(stdout, handleOutputFailure);\nconst diagnosticOutput = createProcessLineWriter(stderr, handleOutputFailure);\n'''
new = '''const helperErrorDetail = (error: unknown): string => {\n  const value = error instanceof Error ? error : new Error(String(error));\n  const stack = typeof value.stack === "string" && value.stack.trim() ? value.stack.trim() : undefined;\n  return (stack ?? `${value.name}: ${value.message}`).slice(0, 12_000);\n};\n\nlet outputFailure: Error | undefined;\nconst handleOutputFailure = (error: Error): void => {\n  if (outputFailure) return;\n  outputFailure = error;\n  void requestShutdown(new Error(`Browser helper output pipe failed: ${error.message}`), 1);\n};\nconst protocolOutput = createProcessLineWriter(stdout, handleOutputFailure);\nconst diagnosticOutput = createProcessLineWriter(stderr, handleOutputFailure);\n'''
if old not in s:
    raise SystemExit('browser-helper output failure block not found')
s = s.replace(old, new, 1)
old = '''let completionFenceRequestId = 0;\nlet shuttingDown = false;\nlet shutdownPromise: Promise<void> | undefined;\n\nfunction requestShutdown(): Promise<void> {\n  if (shutdownPromise) return shutdownPromise;\n  let completeShutdown!: () => void;\n  shutdownPromise = new Promise<void>(resolveShutdown => {\n    completeShutdown = resolveShutdown;\n  });\n  shuttingDown = true;\n  protocolOutput.close();\n  diagnosticOutput.close();\n'''
new = '''let completionFenceRequestId = 0;\nlet shuttingDown = false;\nlet shutdownPromise: Promise<void> | undefined;\nlet shutdownExitCode = 0;\nlet shutdownReasonLogged = false;\n\nfunction requestShutdown(reason?: unknown, exitCode = 0): Promise<void> {\n  shutdownExitCode = Math.max(shutdownExitCode, exitCode);\n  if (reason !== undefined && !shutdownReasonLogged) {\n    shutdownReasonLogged = true;\n    diagnostic(`[browser-helper] shutdown requested exitCode=${shutdownExitCode}\\n${helperErrorDetail(reason)}`);\n  }\n  if (shutdownPromise) return shutdownPromise;\n  let completeShutdown!: () => void;\n  shutdownPromise = new Promise<void>(resolveShutdown => {\n    completeShutdown = resolveShutdown;\n  });\n  shuttingDown = true;\n  // Stop protocol output immediately, but keep stderr alive until worker cleanup finishes. The\n  // previous ordering closed diagnostics first and then attempted to report cleanup failure into\n  // that closed writer, erasing the only explanation for a status-1 helper exit.\n  protocolOutput.close();\n'''
if old not in s:
    raise SystemExit('browser-helper shutdown preamble not found')
s = s.replace(old, new, 1)
old = '''  void closeChatGptBrowserWorkers().then(\n    () => {\n      completeShutdown();\n      process.exit(0);\n    },\n    error => {\n      diagnostic(`Browser helper shutdown failed: ${error instanceof Error ? error.message : String(error)}`);\n      completeShutdown();\n      process.exit(1);\n    },\n  );\n'''
new = '''  void closeChatGptBrowserWorkers().then(\n    () => {\n      diagnostic(`[browser-helper] shutdown complete exitCode=${shutdownExitCode}`);\n      diagnosticOutput.close();\n      completeShutdown();\n      process.exit(shutdownExitCode);\n    },\n    error => {\n      shutdownExitCode = 1;\n      diagnostic(`[browser-helper] shutdown cleanup failed\\n${helperErrorDetail(error)}`);\n      diagnosticOutput.close();\n      completeShutdown();\n      process.exit(1);\n    },\n  );\n'''
if old not in s:
    raise SystemExit('browser-helper shutdown completion block not found')
s = s.replace(old, new, 1)
old = '''  else if (message.type === "shutdown") {\n    void requestShutdown();\n'''
new = '''  else if (message.type === "shutdown") {\n    void requestShutdown(new Error("Browser helper received an explicit shutdown request"));\n'''
if old not in s:
    raise SystemExit('browser-helper explicit shutdown block not found')
s = s.replace(old, new, 1)
old = '''input.on("close", () => {\n  void requestShutdown();\n});\nprocess.once("SIGINT", () => {\n  void requestShutdown();\n});\nprocess.once("SIGTERM", () => {\n  void requestShutdown();\n});\n\n// Advertise optional frames'''
new = '''input.on("close", () => {\n  const activeOperations = abortControllers.size;\n  void requestShutdown(\n    new Error(`Browser helper stdin closed with ${activeOperations} active operation(s)`),\n    activeOperations > 0 ? 1 : 0,\n  );\n});\nprocess.once("SIGINT", () => {\n  void requestShutdown(new Error("Browser helper received SIGINT"));\n});\nprocess.once("SIGTERM", () => {\n  void requestShutdown(new Error("Browser helper received SIGTERM"));\n});\nprocess.once("uncaughtException", error => {\n  void requestShutdown(\n    new Error(`Browser helper uncaughtException\\n${helperErrorDetail(error)}`),\n    1,\n  );\n});\nprocess.once("unhandledRejection", reason => {\n  void requestShutdown(\n    new Error(`Browser helper unhandledRejection\\n${helperErrorDetail(reason)}`),\n    1,\n  );\n});\n\n// Advertise optional frames'''
if old not in s:
    raise SystemExit('browser-helper process event block not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Retain a bounded privacy-safe stderr + protocol-lifecycle tail in the daemon and attach it to
# helper-exit failures. This makes the Codex-visible failure self-diagnosing instead of reducing
# everything to an exit status.
p = Path('src/adapters/chatgpt-web/launcher-helper-client.ts')
s = p.read_text()
anchor = '''interface PendingTurn {\n'''
insert = '''const MAX_HELPER_DIAGNOSTIC_LINES = 48;\nconst MAX_HELPER_LIFECYCLE_ENTRIES = 96;\nconst MAX_HELPER_DIAGNOSTIC_LINE_CHARS = 2_000;\nconst HELPER_FAILURE_DIAGNOSTIC_LINES = 20;\nconst HELPER_FAILURE_LIFECYCLE_ENTRIES = 32;\n\ninterface PendingTurn {\n'''
if anchor not in s:
    raise SystemExit('launcher helper constants anchor not found')
s = s.replace(anchor, insert, 1)
old = '''  private readonly pending = new Map<string, PendingTurn>();\n  private helperFeatures = new Set<string>();\n\n  constructor(private readonly config: ResolvedBrowserConfig) {}\n'''
new = '''  private readonly pending = new Map<string, PendingTurn>();\n  private helperFeatures = new Set<string>();\n  private helperDiagnosticTail: string[] = [];\n  private helperLifecycleTail: string[] = [];\n\n  constructor(private readonly config: ResolvedBrowserConfig) {}\n\n  private recordHelperDiagnostic(line: string): void {\n    const bounded = line.replace(/\\r/g, "").slice(0, MAX_HELPER_DIAGNOSTIC_LINE_CHARS);\n    if (!bounded) return;\n    this.helperDiagnosticTail.push(bounded);\n    if (this.helperDiagnosticTail.length > MAX_HELPER_DIAGNOSTIC_LINES) {\n      this.helperDiagnosticTail.splice(0, this.helperDiagnosticTail.length - MAX_HELPER_DIAGNOSTIC_LINES);\n    }\n  }\n\n  private recordHelperLifecycle(event: string): void {\n    this.helperLifecycleTail.push(`${new Date().toISOString()} ${event}`);\n    if (this.helperLifecycleTail.length > MAX_HELPER_LIFECYCLE_ENTRIES) {\n      this.helperLifecycleTail.splice(0, this.helperLifecycleTail.length - MAX_HELPER_LIFECYCLE_ENTRIES);\n    }\n  }\n\n  private recordHelperMessage(message: HelperMessage): void {\n    if (message.type === "ready") {\n      this.recordHelperLifecycle(`rx ready features=${(message.features ?? []).join(",") || "none"}`);\n      return;\n    }\n    if (message.type === "event") {\n      const revision = "revision" in message ? ` revision=${message.revision}` : "";\n      const requestId = "requestId" in message ? ` requestId=${message.requestId}` : "";\n      this.recordHelperLifecycle(`rx event=${message.event} id=${message.id}${revision}${requestId}`);\n      return;\n    }\n    if (message.type === "error") {\n      this.recordHelperLifecycle(\n        `rx error id=${message.id} name=${message.name ?? "Error"} code=${message.code ?? "none"}`,\n      );\n      return;\n    }\n    this.recordHelperLifecycle(`rx result id=${message.id}`);\n  }\n\n  private helperFailureWithContext(error: Error): Error {\n    const diagnostics = this.helperDiagnosticTail.slice(-HELPER_FAILURE_DIAGNOSTIC_LINES);\n    const lifecycle = this.helperLifecycleTail.slice(-HELPER_FAILURE_LIFECYCLE_ENTRIES);\n    const sections = [error.message];\n    if (diagnostics.length > 0) {\n      sections.push(`helper stderr tail:\\n${diagnostics.map(line => `  ${line}`).join("\\n")}`);\n    }\n    if (lifecycle.length > 0) {\n      sections.push(`helper lifecycle tail:\\n${lifecycle.map(line => `  ${line}`).join("\\n")}`);\n    }\n    return new Error(sections.join("\\n"), { cause: error });\n  }\n'''
if old not in s:
    raise SystemExit('launcher helper class field block not found')
s = s.replace(old, new, 1)
old = '''    const descriptor = readLauncherBrowserHostDescriptor(this.config.browserHostDescriptorPath!);\n    const child = spawn(\n'''
new = '''    const descriptor = readLauncherBrowserHostDescriptor(this.config.browserHostDescriptorPath!);\n    this.helperDiagnosticTail = [];\n    this.helperLifecycleTail = [];\n    const child = spawn(\n'''
if old not in s:
    raise SystemExit('launcher helper spawn anchor not found')
s = s.replace(old, new, 1)
old = '''    this.child = child;\n    this.ready = new Promise<void>((resolveReady, rejectReady) => {\n'''
new = '''    this.child = child;\n    this.recordHelperLifecycle(`spawn pid=${child.pid ?? "unknown"}`);\n    this.ready = new Promise<void>((resolveReady, rejectReady) => {\n'''
if old not in s:
    raise SystemExit('launcher helper spawned-child anchor not found')
s = s.replace(old, new, 1)
old = '''    const errors = createInterface({ input: child.stderr });\n    errors.on("line", line => console.info(`[chatgpt-web-helper] ${line}`));\n'''
new = '''    const errors = createInterface({ input: child.stderr });\n    errors.on("line", line => {\n      this.recordHelperDiagnostic(line);\n      console.info(`[chatgpt-web-helper] ${line}`);\n    });\n'''
if old not in s:
    raise SystemExit('launcher helper stderr handler not found')
s = s.replace(old, new, 1)
old = '''    try { message = parseHelperMessage(line); }\n    catch (error) {\n'''
new = '''    try { message = parseHelperMessage(line); }\n    catch (error) {\n'''
# Keep anchor but add message recording after catch block separately.
if old not in s:
    raise SystemExit('launcher helper handleLine parser not found')
# Insert before ready branch.
old2 = '''      return;\n    }\n    if (message.type === "ready") {\n'''
new2 = '''      return;\n    }\n    this.recordHelperMessage(message);\n    if (message.type === "ready") {\n'''
if old2 not in s:
    raise SystemExit('launcher helper message recording anchor not found')
s = s.replace(old2, new2, 1)
old = '''  private handleExit(child: ChildProcessWithoutNullStreams, error: Error): void {\n    if (this.child !== child) return;\n    this.readyReject?.(error);\n'''
new = '''  private handleExit(child: ChildProcessWithoutNullStreams, error: Error): void {\n    if (this.child !== child) return;\n    this.recordHelperLifecycle(`exit pid=${child.pid ?? "unknown"} code=${child.exitCode ?? "none"} signal=${child.signalCode ?? "none"}`);\n    const contextualError = this.helperFailureWithContext(error);\n    console.error(`[chatgpt-web-helper] ${contextualError.message}`);\n    this.readyReject?.(contextualError);\n'''
if old not in s:
    raise SystemExit('launcher helper handleExit preamble not found')
s = s.replace(old, new, 1)
old = '''        () => this.finishWithError(id, pending.localFailure ?? error),\n        controlError => this.finishWithError(\n          id,\n          new AggregateError(\n            [pending.localFailure ?? error, controlError instanceof Error ? controlError : new Error(String(controlError))],\n            `Launcher browser helper exited and failed to release turn ${id}`,\n          ),\n        ),\n'''
new = '''        () => this.finishWithError(\n          id,\n          pending.localFailure\n            ? new Error(`${pending.localFailure.message}\\n${contextualError.message}`, { cause: pending.localFailure })\n            : contextualError,\n        ),\n        controlError => this.finishWithError(\n          id,\n          new AggregateError(\n            [\n              pending.localFailure ?? contextualError,\n              controlError instanceof Error ? controlError : new Error(String(controlError)),\n            ],\n            `Launcher browser helper exited and failed to release turn ${id}: ${contextualError.message}`,\n          ),\n        ),\n'''
if old not in s:
    raise SystemExit('launcher helper handleExit pending error block not found')
s = s.replace(old, new, 1)
# Add privacy-safe outbound lifecycle breadcrumbs without recording payload contents.
old = '''  private async sendTo(child: ChildProcessWithoutNullStreams, message: unknown): Promise<void> {\n    const encoded = `${JSON.stringify(message)}\\n`;\n'''
new = '''  private async sendTo(child: ChildProcessWithoutNullStreams, message: unknown): Promise<void> {\n    if (message && typeof message === "object" && !Array.isArray(message)) {\n      const frame = message as Record<string, unknown>;\n      const type = typeof frame.type === "string" ? frame.type : "unknown";\n      const id = typeof frame.id === "string" ? frame.id : undefined;\n      this.recordHelperLifecycle(`tx type=${type}${id ? ` id=${id}` : ""}`);\n    }\n    const encoded = `${JSON.stringify(message)}\\n`;\n'''
if old not in s:
    raise SystemExit('launcher helper sendTo anchor not found')
s = s.replace(old, new, 1)
p.write_text(s)

# Regression tests: diagnostics remain live through shutdown, crash hooks exist, and the daemon's
# user-visible error carries both stderr and protocol breadcrumbs while remaining bounded.
p = Path('tests/helper-crash-diagnostics.test.ts')
p.write_text(r'''import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { LauncherBrowserHelperClient } from "../src/adapters/chatgpt-web/launcher-helper-client";

test("browser helper keeps diagnostics writable until shutdown cleanup is reported", () => {
  const source = readFileSync("src/adapters/chatgpt-web/browser-helper-main.ts", "utf8");
  const cleanup = source.indexOf("shutdown cleanup failed");
  const closeAfterCleanup = source.indexOf("diagnosticOutput.close()", cleanup);
  const firstProtocolClose = source.indexOf("protocolOutput.close()");
  const firstDiagnosticClose = source.indexOf("diagnosticOutput.close()", firstProtocolClose);
  expect(cleanup).toBeGreaterThan(-1);
  expect(closeAfterCleanup).toBeGreaterThan(cleanup);
  expect(firstDiagnosticClose).toBeGreaterThan(firstProtocolClose);
  expect(source).toContain('process.once("uncaughtException"');
  expect(source).toContain('process.once("unhandledRejection"');
  expect(source).toContain("active operation(s)");
});

test("helper exit errors include bounded stderr and lifecycle tails", () => {
  const client = new LauncherBrowserHelperClient({
    appName: "Codex Native2",
    browserHost: "launcher",
    browserHostDescriptorPath: "/durable/launcher.json",
    storageStatePath: "/durable/unused-state.json",
    chromeExecutablePath: "/durable/unused-chrome",
    turnTimeoutMs: 60_000,
    headed: true,
    autoApproveToolCalls: false,
  });
  const internal = client as unknown as {
    recordHelperDiagnostic(line: string): void;
    recordHelperLifecycle(event: string): void;
    helperFailureWithContext(error: Error): Error;
    helperDiagnosticTail: string[];
    helperLifecycleTail: string[];
  };
  for (let index = 0; index < 80; index += 1) {
    internal.recordHelperDiagnostic(`stderr-${index}`);
    internal.recordHelperLifecycle(`event-${index}`);
  }
  const error = internal.helperFailureWithContext(new Error("Launcher browser helper exited with status 1"));
  expect(error.message).toContain("Launcher browser helper exited with status 1");
  expect(error.message).toContain("helper stderr tail:");
  expect(error.message).toContain("stderr-79");
  expect(error.message).not.toContain("stderr-0\n");
  expect(error.message).toContain("helper lifecycle tail:");
  expect(error.message).toContain("event-79");
  expect(internal.helperDiagnosticTail.length).toBeLessThanOrEqual(48);
  expect(internal.helperLifecycleTail.length).toBeLessThanOrEqual(96);
});

test("helper lifecycle breadcrumbs never serialize protocol payload text", () => {
  const source = readFileSync("src/adapters/chatgpt-web/launcher-helper-client.ts", "utf8");
  const sendTo = source.slice(source.indexOf("  private async sendTo("));
  expect(sendTo).toContain("tx type=${type}");
  expect(sendTo).not.toContain("JSON.stringify(frame)");
  expect(source).toContain("MAX_HELPER_DIAGNOSTIC_LINE_CHARS");
});
''')
