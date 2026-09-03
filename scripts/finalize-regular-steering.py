from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "launcher/electron/browser-host.cjs",
    'actualUrl.searchParams.get("temporary-chat") !== "true"',
    '!actualUrl.searchParams.has("temporary-chat")',
    "strict regular-session probe",
)

replace_once(
    "launcher/electron/browser-host.cjs",
    "    // existing Temporary Chat document; doing both back-to-back races the helper against a second\n",
    "    // existing regular ChatGPT document; doing both back-to-back races the helper against a second\n",
    "regular refresh comment",
)

# Keep the conversation-key documentation attached to the function it describes.
p = Path("src/adapters/chatgpt-web/conversation-key.ts")
text = p.read_text()
old = '''/** Full history remains canonical; a retained epoch receives only the suffix after its last assistant reply. */\n/** A live Codex steering revision reuses the browser conversation and sends only the new instruction. */\nexport function retainedConversationSteeringRequest'''
new = '''/** A live Codex steering revision reuses the browser conversation and sends only the new instruction. */\nexport function retainedConversationSteeringRequest'''
if text.count(old) != 1:
    raise SystemExit("conversation-key documentation block mismatch")
text = text.replace(old, new, 1)
resume = '''export function retainedConversationResumeRequest(\n'''
if text.count(resume) != 1:
    raise SystemExit("retained resume function mismatch")
text = text.replace(
    resume,
    '''/** Full history remains canonical; a retained epoch receives only the suffix after its last assistant reply. */\n''' + resume,
    1,
)
p.write_text(text)

# Assert the functional runtime contains no URL that activates Temporary Chat.
for path in [
    "src/chatgpt-session.ts",
    "src/adapters/chatgpt-web/browser-worker.ts",
    "launcher/electron/browser-host.cjs",
    "src/launcher-browser-host.ts",
]:
    text = Path(path).read_text()
    if "temporary-chat=true" in text:
        raise SystemExit(f"{path}: still contains a Temporary Chat activation URL")
