from pathlib import Path

# Tighten runtime predicates: regular-only means the temporary-chat query parameter is absent.
for path in ["src/chatgpt-session.ts", "launcher/electron/browser-host.cjs"]:
    p = Path(path)
    text = p.read_text()
    text = text.replace('url.searchParams.get("temporary-chat") === "true"', 'url.searchParams.has("temporary-chat")')
    text = text.replace('parsed.searchParams.get("temporary-chat") !== "true"', '!parsed.searchParams.has("temporary-chat")')
    p.write_text(text)

# Launcher tests should exercise the new product contract, not preserve old Temporary Chat fixtures.
p = Path("launcher/tests/browser-host.test.cjs")
text = p.read_text()
text = text.replace('https://chatgpt.com/?temporary-chat=true', 'https://chatgpt.com/')
text = text.replace('temporary: true', 'regular: true')
text = text.replace('temporary: false', 'regular: false')
text = text.replace('temporary: primaryReady', 'regular: primaryReady')
text = text.replace('temporary: currentUrl === "https://chatgpt.com/"', 'regular: currentUrl === "https://chatgpt.com/"')
text = text.replace('.temporary', '.regular')
text = text.replace('Temporary Chat', 'regular ChatGPT')
# Initial staging already renamed the helper predicate import/calls.
text = text.replace('isTemporaryChatUrl', 'isRegularChatUrl')
p.write_text(text)

# Any other launcher fixtures that describe session evidence should use regular-only semantics.
for path in [
    "launcher/tests/runtime-host.test.cjs",
    "tests/launcher-browser-host.test.ts",
    "tests/browser-worker-contract.test.ts",
    "tests/chatgpt-web-harness.test.ts",
    "tests/personalization-connector-preflight.test.ts",
]:
    p = Path(path)
    if not p.exists():
        continue
    text = p.read_text()
    text = text.replace('https://chatgpt.com/?temporary-chat=true', 'https://chatgpt.com/')
    text = text.replace('temporary: true', 'regular: true')
    text = text.replace('temporary: false', 'regular: false')
    text = text.replace('.temporary', '.regular')
    p.write_text(text)
