"""Render the driver's captures without a browser: *.cells.json → PNG, and session.cast (asciinema v2) → GIF.

The pixels come from the same emulated terminal the driver recorded (pyte); nothing is retyped or edited.
Needs Pillow; the GIF also needs pyte and wcwidth (pyte's own dependency).

    uv run --with pyte --with pillow python3 demo/term_render.py png <capture_dir>
    uv run --with pyte --with pillow python3 demo/term_render.py gif <session.cast> <out.gif> [<last-snap.cells.json>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

BG, FG = "#0E0F12", "#E6E6E6"
MONO = ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
MONO_BOLD = ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",)
SYMBOLS = ("/System/Library/Fonts/Apple Symbols.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
EMOJI = ("/System/Library/Fonts/Apple Color Emoji.ttc", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")


def _font(paths, size, index=0):
    for p in paths:
        try:
            return ImageFont.truetype(p, size, index=index)
        except Exception:
            continue
    return None


def _width(ch: str) -> int:
    try:
        from wcwidth import wcwidth
        w = wcwidth(ch)
        return 2 if w == 2 else 1
    except Exception:
        return 2 if ord(ch) >= 0x1F000 else 1


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF


class Painter:
    def __init__(self, size: int = 15):
        self.size = size
        self.font = _font(MONO, size) or ImageFont.load_default()
        self.bold = _font(MONO, size, index=1) or _font(MONO_BOLD, size) or self.font
        self.cw = int(round(self.font.getlength("M")))
        self.lh = int(round(size * 1.35))
        self._emoji_font = _font(EMOJI, 64) or _font(EMOJI, 109)  # colour bitmap strikes are fixed sizes (40 lacks 🧾)
        self._emoji: Dict[str, Optional[Image.Image]] = {}
        self.symbols = _font(SYMBOLS, size)
        self._tofu = self._mask(self.font, "\ue000")
        self._missing: Dict[str, bool] = {}

    @staticmethod
    def _mask(font, ch):
        try:
            m = font.getmask(ch)
            return (m.size, bytes(m))
        except Exception:
            return None

    def font_for(self, ch: str, font):
        """Menlo has no glyph for some symbols (⏲, ☤): draw those from a symbol font instead of a tofu box."""
        if ord(ch) < 0x2000 or self.symbols is None:
            return font
        if ch not in self._missing:
            self._missing[ch] = self._mask(font, ch) == self._tofu
        return self.symbols if self._missing[ch] else font

    def emoji(self, ch: str) -> Optional[Image.Image]:
        if ch not in self._emoji:
            img = None
            if self._emoji_font is not None:
                try:
                    tile = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
                    ImageDraw.Draw(tile).text((8, 8), ch, font=self._emoji_font, embedded_color=True)
                    box = tile.getbbox()
                    if box:
                        img = tile.crop(box)
                        k = min((2 * self.cw) / img.width, (self.lh - 2) / img.height)  # fit two cells
                        img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))),
                                         Image.Resampling.LANCZOS)
                except Exception:
                    img = None
            self._emoji[ch] = img
        return self._emoji[ch]

    def paint(self, rows: List[List[list]], cols: int, pad: int = 24) -> Image.Image:
        """rows: [[text, fg, bg, bold], ...] per row, as demo/drive.py writes them."""
        w = cols * self.cw + 2 * pad
        h = max(1, len(rows)) * self.lh + 2 * pad
        img = Image.new("RGB", (w, h), BG)
        g = ImageDraw.Draw(img)
        for y, runs in enumerate(rows):
            col = 0
            top = pad + y * self.lh
            for text, fg, bg, bold in runs:
                font = self.bold if bold else self.font
                fill = fg or FG
                span = sum(_width(ch) for ch in text)
                if bg:
                    g.rectangle([pad + col * self.cw, top, pad + (col + span) * self.cw - 1, top + self.lh - 1],
                                fill=bg)
                seg, seg_col = "", col
                for ch in text:
                    wide = _width(ch) == 2
                    if wide or _is_emoji(ch):
                        if seg:
                            g.text((pad + seg_col * self.cw, top), seg, fill=fill, font=font)
                            seg = ""
                        pic = self.emoji(ch) if _is_emoji(ch) else None
                        if pic is not None:
                            img.paste(pic, (pad + col * self.cw + (2 * self.cw - pic.width) // 2,
                                            top + (self.lh - pic.height) // 2), pic)
                        else:
                            g.text((pad + col * self.cw, top), ch, fill=fill, font=font)
                        col += 2 if wide else 1
                        seg_col = col
                        continue
                    alt = self.font_for(ch, font)
                    if alt is not font:
                        if seg:
                            g.text((pad + seg_col * self.cw, top), seg, fill=fill, font=font)
                            seg = ""
                        g.text((pad + col * self.cw, top), ch, fill=fill, font=alt)
                        col += 1
                        seg_col = col
                        continue
                    if not seg:
                        seg_col = col
                    seg += ch
                    col += 1
                if seg:
                    g.text((pad + seg_col * self.cw, top), seg, fill=fill, font=font)
        return img


def pngs(cap_dir: Path) -> List[Path]:
    p = Painter(15)
    out = []
    for f in sorted(cap_dir.glob("*.cells.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        png = f.with_name(f.name[:-len(".cells.json")] + ".png")
        p.paint(data["rows"], data["cols"]).save(png, "PNG", optimize=True)
        out.append(png)
        print(f"{png.name}: {Image.open(png).size[0]}x{Image.open(png).size[1]}")
    return out


COLORS = {"black": "#0E0F12", "red": "#FF6B61", "green": "#2BD67B", "brown": "#FFB627", "yellow": "#FFD166",
          "blue": "#7AA2F7", "magenta": "#C792EA", "cyan": "#5FD7D7", "white": "#E6E6E6", "default": None}


def _color(c, fallback):
    import re
    if c in COLORS:
        return COLORS[c] or fallback
    if re.fullmatch(r"[0-9a-fA-F]{6}", c or ""):
        return "#" + c
    return fallback


def _runs(screen, cols: int, rows: int) -> List[List[list]]:
    out = []
    for y in range(rows):
        line = screen.buffer[y]
        runs, cur, buf = [], None, []
        for x in range(cols):
            ch = line[x]
            if ch.data == "":
                continue  # the second cell of a wide character
            style = (_color(ch.fg, FG) if not ch.reverse else BG,
                     None if ch.bg == "default" and not ch.reverse else (_color(ch.bg, None) if not ch.reverse else FG),
                     bool(ch.bold))
            if style != cur and buf:
                runs.append(["".join(buf), *cur])
                buf = []
            cur = style
            buf.append(ch.data)
        if buf:
            runs.append(["".join(buf), *cur])
        out.append(runs)
    return out


def gif(cast: Path, out: Path, step: float = 0.35, max_hold: float = 2.5, scale: float = 0.62,
        until: Optional[float] = None) -> Path:
    """``until``: stop at this cast time (the driver stores each snap's time in its .cells.json)."""
    import pyte
    lines = cast.read_text(encoding="utf-8").splitlines()
    head = json.loads(lines[0])
    cols, rows = head["width"], head["height"]
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    painter = Painter(15)
    frames: List[Image.Image] = []
    times: List[float] = []
    last_t, last_sig = -1e9, None

    def snap(t):
        nonlocal last_sig
        sig = "\n".join(screen.display)
        if sig == last_sig:
            return
        last_sig = sig
        img = painter.paint(_runs(screen, cols, rows), cols)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
        frames.append(img.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))
        times.append(t)

    for line in lines[1:]:
        try:
            t, kind, data = json.loads(line)
        except Exception:
            continue
        if kind != "o":
            continue
        if until is not None and t > until:
            break
        if t - last_t >= step:
            snap(t)
            last_t = t
        stream.feed(data.encode("utf-8", "replace").replace(b"\xef\xb8\x8f", b""))
    snap(last_t + step)
    if not frames:
        raise SystemExit("empty cast")
    durations = [max(60, int(1000 * min(max_hold, b - a))) for a, b in zip(times, times[1:])] + [4000]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True,
                   disposal=1)
    print(f"{out.name}: {len(frames)} frames, {sum(durations) / 1000:.1f}s, {out.stat().st_size // 1024} KB")
    return out


if __name__ == "__main__":
    if sys.argv[1] == "png":
        pngs(Path(sys.argv[2]))
    elif sys.argv[1] == "gif":
        stop = None
        if len(sys.argv) > 4:  # a snap's .cells.json: end the GIF on that screen (before /exit clears it)
            stop = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))["t"]
        gif(Path(sys.argv[2]), Path(sys.argv[3]), until=stop)
    else:
        raise SystemExit(__doc__)
