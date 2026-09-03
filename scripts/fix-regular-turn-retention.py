from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "src/adapters/chatgpt-web/index.ts",
    "    const retainConversation = conversationKey !== undefined && mode.localTools;",
    "    const retainConversation = conversationKey !== undefined;",
    "retain every regular launcher conversation",
)
replace_once(
    "src/adapters/chatgpt-web/index.ts",
    '''        ...(conversationKey ? { conversationKey } : {}),\n        ...(steeringConversationKey ? { requireRetainedConversation: true } : {}),''',
    '''        ...(retainConversation ? { retainConversation: true, conversationKey } : {}),\n        ...(steeringConversationKey ? { requireRetainedConversation: true } : {}),''',
    "read-only browser turn retention",
)
replace_once(
    "src/adapters/chatgpt-web/index.ts",
    '''        ...(conversationKey ? { conversationKey } : {}),\n        ...(steeringHandoffFor(() => browserTurn.cancel()) ? {''',
    '''        ...(conversationKey ? { conversationKey } : {}),\n        ...(releaseRetainedConversation ? { releaseRetainedConversation } : {}),\n        ...(steeringHandoffFor(() => browserTurn.cancel()) ? {''',
    "read-only retained conversation cleanup",
)
