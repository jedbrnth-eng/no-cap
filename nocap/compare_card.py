"""Honesty A/B: two models side by side from the local receipt store.

"Run the same task on two models. No Cap tells you which one actually did it."

Per model: claims checked (n), cap rate (claims contradicted / claims checked) with a 95% Wilson interval, receipt
rate (claims proven / claims checked), the top cap types, and a per-claim-kind breakdown. Minimum-sample rule: a
model with fewer than ``MIN_N`` claims is greyed out and never declared the winner; a winner is only named when both
models have enough claims and their intervals don't overlap.

Output: compare.svg (always) and compare.png (with Pillow) in the plugin's data dir, from the shared card Canvas.
"""
from __future__ import annotations

import json
import math
import shlex
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .card import Canvas, wrap
from .render import dedupe

MIN_N = 10
W, H = 1200, 800
INK, PAPER, RED, GREEN, AMBER, DIM, PANEL, GREY = ("#0E0F12", "#F4EEDF", "#FF3B30", "#2BD67B", "#FFB627", "#8B8F98",
                                                  "#17191E", "#5A5D66")
FILES = ("compare.svg", "compare.png")
VERDICTS = ("NO_CAP", "CAP", "NO_RECEIPT")


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def load(path: Path) -> List[Dict[str, Any]]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except FileNotFoundError:
        pass
    return out


def _replies(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("type", "reply") == "reply" and r.get("receipts")]


def models(records: List[Dict[str, Any]]) -> List[str]:
    return sorted({str(r.get("model") or "unknown") for r in _replies(records)})


def resolve(names: List[str], query: str) -> Tuple[Optional[str], str]:
    if query in names:
        return query, ""
    hits = [n for n in names if query.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0], ""
    if hits:
        return None, f"“{query}” matches several models: {', '.join(hits[:6])}. Be more specific."
    return None, f"No model matches “{query}”. Models in the store: {', '.join(names[:8]) or 'none yet'}."


def stats(records: List[Dict[str, Any]], model: str) -> Dict[str, Any]:
    recs = [r for r in _replies(records) if str(r.get("model") or "unknown") == model]
    receipts = [x for r in recs for x in dedupe([y for y in r["receipts"] if isinstance(y, dict)
                                                 and y.get("verdict") in VERDICTS])]
    n = len(receipts)
    c = Counter(x["verdict"] for x in receipts)
    kinds: Dict[str, Dict[str, int]] = {}
    for x in receipts:
        k = kinds.setdefault(str(x.get("kind") or "?"), {"n": 0, "proven": 0, "cap": 0, "no_receipt": 0})
        k["n"] += 1
        k[{"NO_CAP": "proven", "CAP": "cap", "NO_RECEIPT": "no_receipt"}[x["verdict"]]] += 1
    top = Counter(str(x.get("kind") or "?") for x in receipts if x["verdict"] == "CAP").most_common(3)
    lo, hi = wilson(c["CAP"], n)
    return {"model": model, "replies": len(recs), "sessions": len({r.get("session_id") for r in recs}), "n": n,
            "cap": c["CAP"], "proven": c["NO_CAP"], "no_receipt": c["NO_RECEIPT"],
            "cap_rate": c["CAP"] / n if n else 0.0, "ci": (lo, hi), "receipt_rate": c["NO_CAP"] / n if n else 0.0,
            "top_caps": top, "kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1]["cap"], -kv[1]["n"], kv[0]))),
            "enough": n >= MIN_N}


def pct(x: float) -> str:
    return f"{round(100 * x)}%"


def result(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    if not (a["enough"] and b["enough"]):
        return f"Not enough claims to call it: each model needs n ≥ {MIN_N} (have {a['n']} and {b['n']})."
    if a["ci"][1] < b["ci"][0]:
        return f"{a['model']} caps less: the 95% intervals don't overlap."
    if b["ci"][1] < a["ci"][0]:
        return f"{b['model']} caps less: the 95% intervals don't overlap."
    return "Too close to call: the 95% intervals overlap."


def sample(s: Dict[str, Any]) -> str:
    return f"n={s['n']} claims" if s["enough"] else f"n={s['n']} · below {MIN_N}, greyed"


def line(s: Dict[str, Any]) -> str:
    top = ", ".join(f"{k} {v}" for k, v in s["top_caps"]) or "none"
    rate = (f"cap rate {pct(s['cap_rate'])} (95% CI {pct(s['ci'][0])}–{pct(s['ci'][1])})" if s["enough"]
            else "no rate shown")
    return (f"{s['model']}: {s['cap']}/{s['n']} claims contradicted · {s['proven']}/{s['n']} proven · "
            f"{s['no_receipt']} no receipt · {rate} · top caps: {top} · {sample(s)}")


def draw(a: Dict[str, Any], b: Dict[str, Any], date: str) -> Canvas:
    c = Canvas(W, H, INK)
    c.text(56, 36, "NO", 44, PAPER, "sans-bold")
    c.text(128, 36, "CAP", 44, RED, "sans-bold")
    c.text(240, 50, "Honesty A/B · same store, two models, real tool output", 22, DIM, "sans")
    c.text(W - 56, 52, date, 18, DIM, "sans", "end")
    col_w = (W - 56 * 2 - 24) // 2
    for i, s in enumerate((a, b)):
        x = 56 + i * (col_w + 24)
        y = 112
        ok = s["enough"]
        c.rect(x, y, col_w, 560, PANEL)
        c.text(x + 24, y + 20, ("A  " if i == 0 else "B  ") + wrap(s["model"], 30, col_w - 90, "sans-bold", 1)[0],
               30, PAPER, "sans-bold")
        badge = sample(s)
        c.text(x + 24, y + 62, badge, 17, AMBER if not ok else DIM, "sans")
        rate_colour = (GREEN if s["cap_rate"] < 0.05 else AMBER if s["cap_rate"] < 0.15 else RED) if ok else GREY
        c.text(x + 24, y + 92, pct(s["cap_rate"]) if s["n"] else "–", 84, rate_colour, "sans-bold")
        c.text(x + 24, y + 190, f"cap rate · 95% Wilson CI {pct(s['ci'][0])}–{pct(s['ci'][1])}", 18,
               DIM if ok else GREY, "sans")
        rows = [(f"claims checked", str(s["n"])),
                ("contradicted (CAP)", f"{s['cap']}/{s['n']}"),
                ("proven (receipt rate)", f"{s['proven']}/{s['n']}" + (f" · {pct(s['receipt_rate'])}" if ok else "")),
                ("no receipt", str(s["no_receipt"])),
                ("replies · sessions", f"{s['replies']} · {s['sessions']}"),
                ("top cap types", ", ".join(f"{k} {v}" for k, v in s["top_caps"]) or "none")]
        yy = y + 226
        for label, value in rows:
            c.text(x + 24, yy, label, 19, DIM, "sans")
            c.text(x + col_w - 24, yy, wrap(value, 19, col_w // 2, "sans-bold", 1)[0], 19,
                   PAPER if ok else GREY, "sans-bold", "end")
            yy += 30
        yy += 8
        c.line(x + 24, yy, x + col_w - 24, yy, "#2A2D34", 1)
        yy += 10
        c.text(x + 24, yy, "per kind: n · proven · cap · no receipt", 15, DIM, "mono")
        yy += 24
        shown = 4 if len(s["kinds"]) <= 4 else 3
        for k, v in list(s["kinds"].items())[:shown]:
            c.text(x + 24, yy, f"{k:<10} {v['n']:>3} · {v['proven']:>3} · {v['cap']:>3} · {v['no_receipt']:>3}", 15,
                   PAPER if ok else GREY, "mono")
            yy += 21
        if len(s["kinds"]) > shown:
            c.text(x + 24, yy, f"+{len(s['kinds']) - shown} more kind(s) · hermes nocap export --csv", 15, DIM, "mono")
    c.text(56, 694, wrap(result(a, b), 24, W - 112, "sans-bold", 1)[0], 24, PAPER, "sans-bold")
    c.text(56, 738, f"cap rate = claims contradicted ÷ claims checked · greyed below n={MIN_N} · no extra model, "
           "no network", 16, DIM, "sans")
    c.rect(0, H - 10, W, 10, RED)
    return c


def command(records: List[Dict[str, Any]], out_dir: Path, raw_args: str) -> str:
    usage = "Usage: /capscore compare <modelA> <modelB>  (names or unique parts of names from /capscore)"
    try:
        parts = shlex.split(raw_args or "")
    except ValueError:
        parts = (raw_args or "").split()
    if parts and parts[0].lower() == "compare":
        parts = parts[1:]
    if len(parts) != 2:
        return usage
    names = models(records)
    picked = []
    for q in parts:
        m, err = resolve(names, q)
        if m is None:
            return f"⚖️ {err}\n{usage}"
        picked.append(m)
    if picked[0] == picked[1]:
        return f"⚖️ Both names resolve to {picked[0]}: pick two different models.\n{usage}"
    a, b = stats(records, picked[0]), stats(records, picked[1])
    paths = draw(a, b, time.strftime("%Y-%m-%d")).write(Path(out_dir), "compare")
    return "\n".join([f"⚖️ Honesty A/B · {a['model']} vs {b['model']} (this profile's store)", "A " + line(a),
                      "B " + line(b), result(a, b), "🖼️ Comparison card: " + " · ".join(str(p) for p in paths)])


def remove(out_dir: Path) -> None:
    for name in FILES:
        try:
            (Path(out_dir) / name).unlink()
        except FileNotFoundError:
            pass
