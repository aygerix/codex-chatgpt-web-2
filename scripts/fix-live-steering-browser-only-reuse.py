from pathlib import Path

path = Path("src/adapters/chatgpt-web/browser-worker.ts")
text = path.read_text()
old = '''      ...((turn.conversationKey\n        && (turn.nativeConnector || turn.capabilities.localToolsEnabled || turn.requireRetainedConversation))\n        ? { connectorIdentity: this.config.appName }\n        : {}),'''
new = '''      ...((turn.conversationKey\n        && (turn.nativeConnector || turn.capabilities.localToolsEnabled))\n        ? { connectorIdentity: this.config.appName }\n        : {}),'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"browser-only steering connector identity: expected one match, found {count}")
path.write_text(text.replace(old, new, 1))
