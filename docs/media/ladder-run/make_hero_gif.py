"""Build the README hero GIF (10 s) from the Lie Ladder captures in this folder.

    python docs/media/ladder-run/make_hero_gif.py      # needs Pillow

Frames, unchanged except for padding to one canvas: 01-rung1 … 05-rung5 (1.5 s each), then verdict.png (2.5 s).
Every frame is a capture from the same `hermes nocap demo --ladder` run; nothing is redrawn.
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
BG = (13, 14, 18)
W, H = 1110, 588
RUNGS = ["01-rung1.png", "02-rung2.png", "03-rung3.png", "04-rung4.png", "05-rung5.png"]


def canvas(img):
    img = img.convert("RGB")
    if img.width > W or img.height > H:
        img.thumbnail((W, H), Image.LANCZOS)
    out = Image.new("RGB", (W, H), BG)
    out.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
    return out


def main():
    frames = [canvas(Image.open(HERE / f)) for f in RUNGS] + [canvas(Image.open(HERE / "verdict.png"))]
    durations = [1500] * len(RUNGS) + [2500]
    frames = [f.resize((W * 3 // 4, H * 3 // 4), Image.LANCZOS) for f in frames]
    pal = [f.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE) for f in frames]
    pal[0].save(HERE / "ladder-10s.gif", save_all=True, append_images=pal[1:], duration=durations, loop=0,
                optimize=True, disposal=1)
    print("wrote", HERE / "ladder-10s.gif", f"{sum(durations) / 1000:.1f}s", len(frames), "frames")


if __name__ == "__main__":
    main()
