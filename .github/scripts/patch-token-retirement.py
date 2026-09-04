from pathlib import Path

p = Path('src/adapters/chatgpt-web/index.ts')
s = p.read_text()
old = '''          if (session.runtime.mode === "tools") {
            void session.runtime.token.then(turnToken => broker.revoke(turnToken)).catch(() => {});
          }
'''
if old not in s:
    raise SystemExit('eager revoke block not found')
s = s.replace(old, '''          // Do not revoke the turn capability here. A Responses/SSE observer can fail or reconnect
          // while the already-accepted browser turn is still alive and may still invoke Codex Native.
          // ChatGptTurnSession owns capability retirement and performs it only after physical browser
          // settlement plus all already-admitted observers have drained.
''', 1)
p.write_text(s)

tp = Path('tests/turn-broker-lifecycle.test.ts')
ts = tp.read_text()
old_import = 'import { ChatGptTextFeed, ChatGptTraceFeed, ChatGptTurnSessions } from "../src/adapters/chatgpt-web/turn-execution";'
new_import = 'import { ChatGptTextFeed, ChatGptTraceFeed, ChatGptTurnSession, ChatGptTurnSessions } from "../src/adapters/chatgpt-web/turn-execution";'
if old_import in ts:
    ts = ts.replace(old_import, new_import, 1)
name = 'accepted browser turn keeps its tool capability across observer failure until physical settlement'
if name not in ts:
    ts += r'''

test("accepted browser turn keeps its tool capability across observer failure until physical settlement", async () => {
  let resolvePhysical!: () => void;
  const physicalSettlement = new Promise<void>(resolve => { resolvePhysical = resolve; });
  let revoked = 0;
  const runtime = {
    mode: "tools" as const,
    browser: new Promise<string>(() => {}),
    physicalSettlement,
    trace: { drain: () => [], wait: async () => {} } as any,
    text: { drain: () => [], value: () => "", wait: async () => {} } as any,
    token: Promise.resolve("turn_token"),
    externalProgress: {} as any,
    retireCapability: async () => { revoked += 1; },
    cancel: () => {},
  };
  const session = new ChatGptTurnSession(runtime as any, "trace", "owner");

  await session.runExclusive(async () => {
    throw new Error("observer disconnected");
  }).catch(() => {});

  await Promise.resolve();
  expect(revoked).toBe(0);

  resolvePhysical();
  await physicalSettlement;
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(revoked).toBe(1);
});
'''
tp.write_text(ts)
