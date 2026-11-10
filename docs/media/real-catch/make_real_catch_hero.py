"""README hero still: the last screen of real-catch.cast at 2x, cropped to the catch.

    uv run --with pyte --with pillow --with wcwidth python3 docs/media/real-catch/make_real_catch_hero.py [full_2x.png]

Same recorded text as real-catch.gif and real-catch-poster.png (see make_real_catch.py): nothing is retyped. The
crop starts at the "short test summary info" line of the model's own `pytest -q` output and ends at No Cap's footer,
so the picture holds, top to bottom, "1 failed", the reply's "All tests pass." and the 🧢 CAP line. Every row between
those two is shown. The cast's first label line is kept above the crop. Pass a path to also save the uncropped 2x screen.
"""
import json
import sys
from pathlib import Path

import pyte
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "demo"))
import term_render as TR  # noqa: E402

SIZE, PAD = 30, 24
lines = (HERE / "real-catch.cast").read_text(encoding="utf-8").splitlines()
head = json.loads(lines[0])
cols, rows = head["width"], head["height"]
screen = pyte.Screen(cols, rows)
stream = pyte.ByteStream(screen)
for ln in lines[1:]:
    stream.feed(json.loads(ln)[2].encode("utf-8").replace(b"\xef\xb8\x8f", b""))
text = ["".join(screen.buffer[y][x].data for x in range(cols)).rstrip() for y in range(rows)]
first = next(i for i, t in enumerate(text) if "short test summary info" in t)
last = max(i for i, t in enumerate(text) if t.strip())
img = TR.Painter(SIZE).paint(TR._runs(screen, cols, rows), cols, PAD)
lh = (img.height - 2 * PAD) / rows
if len(sys.argv) > 1:
    img.save(sys.argv[1], "PNG", optimize=True)
label = img.crop((0, 0, img.width, round(PAD + lh)))  # the cast's first label line (the second is about the GIF's timing)
body = img.crop((0, round(PAD + first * lh), img.width, round(PAD + (last + 1) * lh + PAD)))
gap = round(lh * 0.6)
out = Image.new("RGB", (img.width, label.height + gap + body.height), img.getpixel((2, 2)))
out.paste(label, (0, 0))
out.paste(body, (0, label.height + gap))
out.save(HERE / "real-catch-hero.png", "PNG", optimize=True)
print("rows", first, "to", last, "of", rows, "->", out.size, "full", img.size)
