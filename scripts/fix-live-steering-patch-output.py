from pathlib import Path
import subprocess


def main_source(path: str) -> str:
    return subprocess.check_output(["git", "show", f"origin/main:{path}"], text=True)


path = "src/chatgpt-session.ts"
text = main_source(path)
start = text.index('export type ChatGptChatSurface = "regular" | "temporary";')
end_marker = 'export const CHATGPT_TEMPORARY_CHAT_URL = CHATGPT_NEW_CHAT_URL;\n'
end = text.index(end_marker, start) + len(end_marker)
text = text[:start] + '''export const CHATGPT_REGULAR_CHAT_URL = "https://chatgpt.com/";\nexport const CHATGPT_NEW_CHAT_URL = CHATGPT_REGULAR_CHAT_URL;\n\n/** Legacy import name retained for the browser worker; it now always means regular ChatGPT. */\nexport const CHATGPT_TEMPORARY_CHAT_URL = CHATGPT_NEW_CHAT_URL;\n''' + text[end:]

assertion_start = text.index('/**\n * Backward-compatible assertion used by the browser worker.')
detect_marker = '\n\nexport async function detectChatGptAccountCapabilities'
assertion_end = text.index(detect_marker, assertion_start)
text = text[:assertion_start] + '''/** Legacy assertion name retained for the worker; only regular/history-backed chats are valid. */\nexport async function assertTemporaryChatPage(page: Page): Promise<void> {\n  const url = new URL(page.url());\n  const expected = new URL(CHATGPT_NEW_CHAT_URL);\n  if (url.origin !== expected.origin || url.searchParams.get("temporary-chat") === "true") {\n    throw new Error(`ChatGPT left the regular chat surface (${page.url()})`);\n  }\n}''' + text[assertion_end:]
Path(path).write_text(text)
