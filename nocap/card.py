"""Shareable Cap Score card, in the brand kit's look.

scorecard.svg is always written: the brand template (assets/share-card.template.svg) filled with stdlib only,
every value XML-escaped, no images, no web fonts, nothing fetched. scorecard.png is added when Pillow is
importable (it ships with Hermes): the same numbers and palette drawn directly, since Pillow can't render
SVG. The PNG is the one to paste into Discord or Telegram, which don't show SVG inline.
"""
from __future__ import annotations

import re
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

TEMPLATE = Path(__file__).with_name("assets") / "share-card.template.svg"
W, H = 1200, 630
BAR_W = 624
MIN_CLAIMS = 20  # below this the card says the sample is too small to rank
INK, PAPER, RED, GREEN, AMBER, DIM, PANEL = "#0E0F12", "#F4EEDF", "#FF3B30", "#2BD67B", "#FFB627", "#8B8F98", "#17191E"


def verdict(rate: float, claims: int) -> str:
    if claims < MIN_CLAIMS:
        return "Too early to call."
    if rate == 0:
        return "Zero cap. Certified."
    if rate < 0.05:
        return "Mostly facts."
    if rate < 0.15:
        return "A little cap."
    return "Cap detected. Check the receipts."


def _numbers(row: Dict[str, Any]) -> Dict[str, Any]:
    n = lambda k: max(0, int(row.get(k) or 0))
    replies, capped = n("replies"), min(n("capped"), n("replies"))
    no_cap, nr = n("proven"), n("no_receipt")
    cap = max(0, n("claims") - no_cap - nr)
    claims = no_cap + nr + cap
    rate = capped / replies if replies else 0.0
    model = " ".join(str(row.get("name") or "unknown").split())
    model = model if len(model) <= 34 else model[:33] + "…"
    return {"model": model, "replies": replies, "capped": capped, "no_cap": no_cap, "no_receipt": nr, "cap": cap,
            "claims": claims, "rate": rate, "streak": n("streak")}


def _rate_text(rate: float) -> str:
    return f"{rate:.0%}" if rate == 0 or rate >= 0.1 else f"{rate:.1%}"


def _rate_color(rate: float) -> str:
    return GREEN if rate < 0.05 else (AMBER if rate < 0.15 else RED)


def _sample(claims: int) -> str:
    return f"n={claims} claims" if claims >= MIN_CLAIMS else f"n={claims} · too few to rank"


def values(row: Dict[str, Any], date: str, badge: str = "") -> Dict[str, str]:
    d = _numbers(row)
    claims = d["claims"]
    w = lambda k: round(BAR_W * k / claims) if claims else 0
    w_nc, w_nr = w(d["no_cap"]), w(d["no_receipt"])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must be YYYY-MM-DD")
    return {
        "model": escape(d["model"]),
        "model_size": str(46 if len(d["model"]) <= 20 else max(26, int(46 * 20 / len(d["model"])))),
        "cap_rate": _rate_text(d["rate"]), "rate_color": _rate_color(d["rate"]),
        "verdict": escape(verdict(d["rate"], claims)),
        "streak": str(d["streak"]), "no_cap": str(d["no_cap"]), "cap": str(d["cap"]),
        "no_receipt": str(d["no_receipt"]), "claims": str(claims), "replies": str(d["replies"]),
        "capped": str(d["capped"]), "w_no_cap": str(w_nc), "x_no_receipt": str(w_nc), "w_no_receipt": str(w_nr),
        "x_cap": str(w_nc + w_nr), "w_cap": str(BAR_W - w_nc - w_nr if claims else 0),
        "date": escape(date), "sample": escape(_sample(claims)), "badge": escape(badge),
    }


def fill(row: Dict[str, Any], date: str, badge: str = "") -> str:
    v = values(row, date, badge)
    out = re.sub(r"\{\{([a-z_]+)\}\}", lambda m: v[m.group(1)], TEMPLATE.read_text(encoding="utf-8"))
    if "{{" in out:
        raise ValueError("share card template has an unknown placeholder")
    return out


def render_png(row: Dict[str, Any], date: str, out: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont  # Pillow is a core Hermes dependency

    def font(size):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    d = _numbers(row)
    img = Image.new("RGB", (W, H), INK)
    g = ImageDraw.Draw(img)
    g.rectangle([0, H - 10, W, H], fill=RED)
    g.text((56, 46), "NO", fill=PAPER, font=font(54))
    g.text((150, 46), "CAP", fill=RED, font=font(54))
    g.text((56, 112), "Cap Score · receipts for agent claims", fill=DIM, font=font(24))
    g.text((56, 180), d["model"], fill=PAPER, font=font(44 if len(d["model"]) <= 20 else 30))
    g.text((52, 260), _rate_text(d["rate"]), fill=_rate_color(d["rate"]), font=font(120))
    g.text((56, 400), f"replies capped ({d['capped']}/{d['replies']}) · {verdict(d['rate'], d['claims'])}",
           fill=PAPER, font=font(26))
    x, y = 56, 456
    g.rectangle([x, y, x + BAR_W, y + 18], fill=PANEL)
    if d["claims"]:
        for count, colour in ((d["no_cap"], GREEN), (d["no_receipt"], AMBER), (d["cap"], RED)):
            w = round(BAR_W * count / d["claims"])
            if w:
                g.rectangle([x, y, x + w, y + 18], fill=colour)
            x += w
    g.text((56, 490), f"{d['streak']} no cap in a row", fill=PAPER, font=font(28))
    px = 760
    g.rectangle([px, 150, W - 56, 560], fill=PAPER)
    g.text((px + 24, 170), f"{date} · {_sample(d['claims'])}", fill="#5b5e66", font=font(18))
    for i, (label, count, colour) in enumerate((("NO CAP (proven)", d["no_cap"], "#178a4c"),
                                                ("NO RECEIPT", d["no_receipt"], "#a86e00"),
                                                ("CAP (contradicted)", d["cap"], "#d42a20"))):
        yy = 220 + i * 62
        g.text((px + 24, yy), label, fill=INK, font=font(24))
        g.text((W - 120, yy - 4), str(count), fill=colour, font=font(30))
    g.text((px + 24, 420), f"claims {d['claims']} · capped {d['capped']}/{d['replies']}", fill=INK, font=font(20))
    g.text((px + 24, 456), f"streak {d['streak']}", fill=INK, font=font(20))
    g.text((56, H - 50), "a Hermes plugin · checked against real tool output · no extra model, no network",
           fill=DIM, font=font(20))
    img.save(out, "PNG")
    return out


def pick(rows: List[Dict[str, Any]], model: Optional[str]) -> Optional[Dict[str, Any]]:
    """The session's model when it has a row, else the most-capped model."""
    for r in rows:
        if model and r["name"] == model:
            return r
    return rows[0] if rows else None


def render(rows: List[Dict[str, Any]], out_dir: Path, model: Optional[str] = None, badge: str = "") -> List[Path]:
    row = pick(rows, model)
    if row is None:
        return []
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    svg = out_dir / "scorecard.svg"
    svg.write_text(fill(row, date, badge), encoding="utf-8")
    paths = [svg]
    try:
        paths.insert(0, render_png(row, date, out_dir / "scorecard.png"))
    except Exception:  # Pillow missing or broken: the SVG alone is still a complete card
        pass
    return paths


# ---- shared canvas for the verdict and compare cards -------------------------------------------------------------
# One list of draw operations rendered twice: as an SVG (stdlib, every string XML-escaped, no images, no web fonts,
# nothing fetched) and, when Pillow is importable, as a PNG with the same layout. Local system fonts only.

FAMILIES = {
    "serif": ("Georgia, 'Times New Roman', serif",
              ("/System/Library/Fonts/Supplemental/Georgia.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "C:/Windows/Fonts/georgia.ttf")),
    "serif-bold": ("Georgia, 'Times New Roman', serif",
                   ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
                    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "C:/Windows/Fonts/georgiab.ttf")),
    "mono": ("ui-monospace, Menlo, Consolas, monospace",
             ("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "C:/Windows/Fonts/consola.ttf")),
    "sans": ("-apple-system, 'Helvetica Neue', Arial, sans-serif",
             ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf")),
    "sans-bold": ("-apple-system, 'Helvetica Neue', Arial, sans-serif",
                  ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf")),
}
CHAR_W = {"serif": 0.52, "serif-bold": 0.56, "mono": 0.64, "sans": 0.53, "sans-bold": 0.58}


def wrap(text: str, size: int, width_px: int, family: str = "serif", max_lines: int = 3):
    """Character-count wrap from an average glyph width, the same for SVG and PNG, so both cards break alike."""
    import textwrap
    chars = max(8, int(width_px / (CHAR_W.get(family, 0.55) * size)))
    lines = textwrap.wrap(" ".join(str(text or "").split()), chars) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, chars - 1)].rstrip() + "…"
    return lines


class Canvas:
    def __init__(self, w: int, h: int, bg: str):
        self.w, self.h, self.bg = w, h, bg
        self.ops: List[tuple] = []

    def rect(self, x, y, w, h, fill, stroke=None, width=1):
        self.ops.append(("rect", x, y, w, h, fill, stroke, width))

    def line(self, x1, y1, x2, y2, color, width=1):
        self.ops.append(("line", x1, y1, x2, y2, color, width))

    def text(self, x, y, s, size, fill, family="serif", anchor="start"):
        """``y`` is the top of the text box."""
        self.ops.append(("text", x, y, str(s), size, fill, family, anchor))

    def svg(self) -> str:
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
               f'viewBox="0 0 {self.w} {self.h}" role="img">',
               f'<rect width="{self.w}" height="{self.h}" fill="{self.bg}"/>']
        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, stroke, width = op
                s = f' stroke="{stroke}" stroke-width="{width}"' if stroke else ""
                out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill or "none"}"{s}/>')
            elif op[0] == "line":
                _, x1, y1, x2, y2, color, width = op
                out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')
            else:
                _, x, y, s, size, fill, family, anchor = op
                fam = FAMILIES.get(family, FAMILIES["serif"])[0]
                weight = ' font-weight="700"' if family.endswith("-bold") else ""
                out.append(f'<text x="{x}" y="{round(y + size * 0.82, 1)}" font-family="{escape(fam)}" '
                           f'font-size="{size}"{weight} fill="{fill}" text-anchor="{anchor}">{escape(s)}</text>')
        out.append("</svg>")
        return "\n".join(out) + "\n"

    def png(self, out: Path) -> Path:
        from PIL import Image, ImageDraw, ImageFont  # Pillow is a core Hermes dependency
        cache: Dict[tuple, Any] = {}

        def font(family, size):
            key = (family, size)
            if key not in cache:
                f = None
                for p in FAMILIES.get(family, FAMILIES["serif"])[1]:
                    try:
                        f = ImageFont.truetype(p, size)
                        break
                    except Exception:
                        continue
                if f is None:
                    try:
                        f = ImageFont.load_default(size=size)
                    except TypeError:
                        f = ImageFont.load_default()
                cache[key] = f
            return cache[key]

        img = Image.new("RGB", (self.w, self.h), self.bg)
        g = ImageDraw.Draw(img)
        for op in self.ops:
            if op[0] == "rect":
                _, x, y, w, h, fill, stroke, width = op
                g.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=width if stroke else 0)
            elif op[0] == "line":
                _, x1, y1, x2, y2, color, width = op
                g.line([x1, y1, x2, y2], fill=color, width=width)
            else:
                _, x, y, s, size, fill, family, anchor = op
                a = {"start": "la", "middle": "ma", "end": "ra"}[anchor]
                try:
                    g.text((x, y), s, fill=fill, font=font(family, size), anchor=a)
                except (ValueError, TypeError):  # a bitmap fallback font has no anchors
                    g.text((x, y), s, fill=fill, font=font(family, size))
        img.save(out, "PNG")
        return out

    def write(self, out_dir: Path, stem: str) -> List[Path]:
        """``stem``.svg always; ``stem``.png too when Pillow works. The PNG is listed first (the one to paste)."""
        out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        svg = out_dir / f"{stem}.svg"
        svg.write_text(self.svg(), encoding="utf-8")
        paths = [svg]
        try:
            paths.insert(0, self.png(out_dir / f"{stem}.png"))
        except Exception:  # Pillow missing or broken: the SVG alone is a complete card
            pass
        return paths
