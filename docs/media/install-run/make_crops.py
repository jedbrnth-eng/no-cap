"""README crop of the open-chip capture. Pixels are copied, not edited: only the empty window area is cut.

    uv run --with pillow python3 docs/media/install-run/make_crops.py
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
BOX = (528, 64, 1808, 664)   # the chat column of the 2560x1640 window, from the prompt to below the open receipt
for src in ("04-chip-open.png",):
    im = Image.open(HERE / src).convert("RGB").crop(BOX)
    out = HERE / src.replace(".png", "-crop.png")
    im.save(out, "PNG", optimize=True)
    print(out.name, im.size)
