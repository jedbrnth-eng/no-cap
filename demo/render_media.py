"""Turn the driver's .html screen captures into PNGs with `om still` (headless Chrome). Text is not edited:
the HTML is the emulated terminal screen, cell for cell, with its colours.

    python3 demo/render_media.py docs/media/demo-run
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LINE_PX, PAD_Y, WIDTH = 15 * 1.35, 56, 1180

out = Path(sys.argv[1])
if not shutil.which("om"):
    print("om not found: skipping PNG renders (the .txt and .html captures are complete)")
    sys.exit(0)
fails = 0
card = out / "scorecard.svg"
if card.exists():  # the brand-template card exactly as /capscore card wrote it, rasterised for viewing
    d = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    body = card.read_text(encoding="utf-8").replace("<svg ", '<svg style="display:block;width:1200px;height:630px" ', 1)
    (d / "card.html").write_text("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0}</style>"
                                 "</head><body><div data-composition-id='card' data-width='1200' data-height='630' "
                                 f"style='width:1200px;height:630px'>{body}</div></body></html>", encoding="utf-8")
    r = subprocess.run(["om", "still", str(d / "card.html"), "--out", str((out / "scorecard-svg.png").resolve())],
                       capture_output=True, text=True, timeout=180)
    print(f"scorecard-svg.png: {'ok' if r.returncode == 0 else 'FAILED'}")
    fails += r.returncode != 0
for page in sorted(out.glob("*.html")):
    if page.name.endswith(".still.html"):
        continue
    text = page.read_text(encoding="utf-8")
    pre = re.search(r"<pre>(.*)</pre>", text, re.S).group(1)
    rows = pre.count("\n") + 1
    h = int(rows * LINE_PX + PAD_Y + 8)
    style = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
    still = (f"<!doctype html><html><head><meta charset='utf-8'><style>{style}</style></head><body>"
             f"<div data-composition-id='shot' data-width='{WIDTH}' data-height='{h}' "
             f"style='width:{WIDTH}px;height:{h}px;background:#0E0F12'><pre>{pre}</pre></div></body></html>")
    d = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    src = d / "shot.html"
    src.write_text(still, encoding="utf-8")
    png = page.with_suffix(".png")
    r = subprocess.run(["om", "still", str(src), "--out", str(png.resolve())], capture_output=True, text=True,
                       timeout=180)
    print(f"{png.name}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:200]} ({WIDTH}x{h})")
    fails += r.returncode != 0
sys.exit(1 if fails else 0)
