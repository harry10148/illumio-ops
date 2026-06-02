import re, glob

# common emoji + dingbat/symbol glyphs used as UI decoration
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF✅✔✖❌✗✘✨"
    "⚠⚙✏✓✕️]"
)
def test_no_emoji_in_frontend():
    bad = []
    for f in glob.glob("src/static/js/*.js") + glob.glob("src/templates/*.html"):
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if EMOJI.search(line):
                bad.append(f"{f}:{i}: {line.strip()[:70]}")
    assert not bad, "emoji found:\n" + "\n".join(bad)
