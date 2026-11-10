"""Paint the recorder's own cell captures (NN-rungN.cells.json, written by demo/drive.py) at 2x for the README.

    uv run --with pillow --with wcwidth python3 docs/media/ladder-run-0.2.1/render_2x.py

The cells are the terminal's recorded characters and colours; this only draws them larger (30 px instead of 15)
and starts each picture at that rung's prompt line. Nothing is retyped.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "demo"))
import term_render as TR  # noqa: E402

for name in ("01-rung1", "06-rung6"):
    data = json.loads((HERE / f"{name}.cells.json").read_text(encoding="utf-8"))
    rows = data["rows"]
    text = ["".join(run[0] for run in r) for r in rows]
    start = max(i for i, t in enumerate(text) if t.lstrip().startswith("❯ Rung"))
    img = TR.Painter(30).paint(rows[max(0, start - 1):], data["cols"])
    img.save(HERE / f"{name}@2x.png", "PNG", optimize=True)
    print(name, img.size)
