from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1))


# The daemon owns the private launcher control token but does not know the detached
# browser-helper PID. Let the launcher resolve that PID from the exact trace+conversation.
replace_once(
    "launcher/electron/steering-handoff.cjs",
    "function ownedTurnTab(host, traceId, helperPid, conversationKey) {",
    "function ownedTurnTab(host, traceId, conversationKey) {",
    "steering tab resolver signature",
)
replace_once(
    "launcher/electron/steering-handoff.cjs",
    '''  if (tab.helperPid !== helperPid) {\n    throw new Error(`Browser helper ownership mismatch: expected ${tab.helperPid}, received ${helperPid}`);\n  }\n''',
    "",
    "steering helper pid validation",
)
replace_once(
    "launcher/electron/steering-handoff.cjs",
    "async function requestSteeringHandoff(host, { traceId, helperPid, conversationKey, connectorBound }) {\n  const tab = ownedTurnTab(host, traceId, helperPid, conversationKey);",
    "async function requestSteeringHandoff(host, { traceId, conversationKey, connectorBound }) {\n  const tab = ownedTurnTab(host, traceId, conversationKey);",
    "steering request signature",
)
replace_once(
    "launcher/electron/steering-handoff.cjs",
    '''    traceId,\n    helperPid,\n    conversationKey,''',
    '''    traceId,\n    helperPid: tab.helperPid,\n    conversationKey,''',
    "steering captures launcher helper pid",
)

replace_once(
    "launcher/electron/control-server.cjs",
    '''      if (!Number.isInteger(body.helperPid) || body.helperPid < 1) {\n        throw new Error("browser helper pid is invalid");\n      }''',
    '''      if (request.url !== "/v1/turn/handoff"\n        && (!Number.isInteger(body.helperPid) || body.helperPid < 1)) {\n        throw new Error("browser helper pid is invalid");\n      }''',
    "control server handoff helper pid exception",
)
replace_once(
    "launcher/electron/control-server.cjs",
    '''          traceId: body.traceId,\n          helperPid: body.helperPid,\n          conversationKey: body.conversationKey,''',
    '''          traceId: body.traceId,\n          conversationKey: body.conversationKey,''',
    "control server handoff body",
)

replace_once(
    "src/launcher-browser-host.ts",
    "  input: { traceId: string; helperPid: number; conversationKey: string; connectorBound?: boolean },",
    "  input: { traceId: string; conversationKey: string; connectorBound?: boolean },",
    "launcher steering client input",
)
replace_once(
    "src/launcher-browser-host.ts",
    '''  if (!Number.isInteger(input.helperPid) || input.helperPid < 1) throw new Error("Launcher steering helper pid is invalid");\n''',
    "",
    "launcher steering client pid validation",
)
replace_once(
    "src/adapters/chatgpt-web/index.ts",
    '''            traceId,\n            helperPid: process.pid,\n            conversationKey,''',
    '''            traceId,\n            conversationKey,''',
    "adapter steering handoff pid",
)

replace_once(
    "launcher/tests/steering-handoff.test.cjs",
    '''    traceId: tab.traceId,\n    helperPid: 42,\n    conversationKey: tab.conversationKey,''',
    '''    traceId: tab.traceId,\n    conversationKey: tab.conversationKey,''',
    "steering test request pid",
)
