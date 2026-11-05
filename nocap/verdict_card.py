"""/nocap verdict: one session's receipts as a courtroom verdict card.

The caption names the model and the session, each claim is a numbered finding with its evidence citation
(turn.call, the command, the exit code, the quoted output), and the closing sentence is computed from the counts.
Wording rule: counts always; a percentage only once a session has at least ``PCT_MIN`` claims, because "80% truthful"
from five claims is noise dressed up as a number.

Output: verdict.svg (always) and verdict.png (when Pillow is importable) in the plugin's data dir, written with the
shared card Canvas: every string escaped, no images, no remote fonts, nothing fetched.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .card import Canvas, wrap
from .render import claim_text, dedupe

CAP, NO_CAP, NO_RECEIPT = "CAP", "NO_CAP", "NO_RECEIPT"
PCT_MIN = 10
MAX_SHOWN = 10
W = 1200
PAPER, INK, DIM, RULE = "#F4EEDF", "#0E0F12", "#5B5E66", "#C9BFA6"
STAMP = {CAP: ("#D42A20", "CAP"), NO_CAP: ("#178A4C", "NO CAP"), NO_RECEIPT: ("#A86E00", "NO RECEIPT")}
FILES = ("verdict.svg", "verdict.png")

# A 🤔 is a count of an unsupported claim, named by what it claimed. A 🧢 is a count of contradiction.
UNSUPPORTED = {
    "deployed": "unsupported deployment", "merged": "unsupported merge", "pr_opened": "unsupported PR",
    "sha": "unverified SHA", "pushed": "unsupported push", "committed": "unsupported commit",
    "tests": "unsupported test claim", "build": "unsupported build", "ci": "unsupported CI claim",
    "url": "unsupported URL claim", "file": "unsupported file claim", "number": "unsupported number",
}


def _plural(n: int, noun: str) -> str:
    return f"{n} count{'s' if n != 1 else ''} of {noun}"


def counts_of(findings: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    """[(noun, count)]: contradiction first, then each unsupported kind in the order it first appeared."""
    out: List[Tuple[str, int]] = []
    caps = sum(1 for f in findings if f["verdict"] == CAP)
    if caps:
        out.append(("contradiction", caps))
    seen: Counter = Counter()
    order: List[str] = []
    for f in findings:
        if f["verdict"] == NO_RECEIPT:
            noun = UNSUPPORTED.get(f.get("kind", ""), "unsupported claim")
            if noun not in seen:
                order.append(noun)
            seen[noun] += 1
    out += [(noun, seen[noun]) for noun in order]
    return out


def sentence(findings: List[Dict[str, Any]]) -> str:
    n = len(findings)
    if not n:
        return "No claims on the record."
    proven = sum(1 for f in findings if f["verdict"] == NO_CAP)
    head = f"{proven} of {n} claim{'s' if n != 1 else ''} proven"
    counts = counts_of(findings)
    tail = ", ".join(_plural(c, noun) for noun, c in counts) if counts else "no counts"
    pct = f" {round(100 * proven / n)}% proven (n={n})." if n >= PCT_MIN else ""
    return f"{head}; {tail}.{pct}"


def ruling(findings: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(headline, colour). Deterministic from the counts."""
    if not findings:
        return "NO CASE. Nothing was claimed.", DIM
    caps = sum(1 for f in findings if f["verdict"] == CAP)
    if caps:
        return f"CAPPED on {caps} count{'s' if caps != 1 else ''}. The receipts say otherwise.", STAMP[CAP][0]
    if any(f["verdict"] == NO_RECEIPT for f in findings):
        return "NOT PROVEN. The court wants receipts.", STAMP[NO_RECEIPT][0]
    return "NO CAP. Acquitted on every count.", STAMP[NO_CAP][0]


def short_id(sid: str) -> str:
    sid = str(sid or "")
    if len(sid) <= 12:
        return sid or "(none)"
    parts = [p for p in re.split(r"[_\-:]", sid) if p]
    return parts[-1] if parts and 4 <= len(parts[-1]) <= 12 else sid[-8:]


def citation(r: Dict[str, Any], turn: int) -> str:
    if r.get("cite") is None:
        return f"No exhibit: {r.get('why') or 'no tool call backs it'}"
    what = r.get("cmd") or r.get("tool") or "tool call"
    out = f"Exhibit {turn}.{r['cite']}: `{' '.join(str(what).split())[:70]}`"
    if r.get("exit") is not None:
        out += f" exit {r['exit']}"
    if r.get("quote"):
        out += f" · “{' '.join(str(r['quote']).split())[:90]}”"
    if r.get("why") and r["verdict"] != NO_CAP:
        out += f" · {r['why']}"
    return out


def session_records(records: List[Dict[str, Any]], session_id: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    replies = [r for r in records if r.get("type", "reply") == "reply"]
    if not session_id:
        with_receipts = [r for r in replies if r.get("receipts")]
        session_id = str(with_receipts[-1].get("session_id") or "") if with_receipts else ""
    return session_id, [r for r in replies if r.get("session_id") == session_id]


def findings_of(recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for turn, rec in enumerate(recs, 1):
        for r in dedupe([x for x in rec.get("receipts") or [] if isinstance(x, dict) and x.get("verdict") in STAMP]):
            out.append({"turn": turn, "verdict": r["verdict"], "kind": r.get("kind", ""), "claim": claim_text(r),
                        "cite": citation(r, turn), "hidden": bool(r.get("hidden")), "receipt": r})
    return out


def model_of(recs: List[Dict[str, Any]]) -> str:
    models = Counter(str(r.get("model") or "unknown") for r in recs)
    name = " ".join((models.most_common(1)[0][0] if models else "unknown").split())
    return name if len(name) <= 48 else name[:47] + "…"


def draw(model: str, session_id: str, findings: List[Dict[str, Any]], replies: int, date: str) -> Canvas:
    c = Canvas(W, 100, PAPER)
    m = 56
    y = 40
    c.text(W // 2, y, "THE COURT OF RECEIPTS · NO CAP DIVISION", 17, DIM, "sans-bold", "middle")
    y += 34
    for line in wrap(f"In re: {model}, session {short_id(session_id)}", 40, W - 2 * m, "serif-bold", 2):
        c.text(W // 2, y, line, 40, INK, "serif-bold", "middle")
        y += 50
    c.text(W // 2, y + 2, f"{len(findings)} claim{'s' if len(findings) != 1 else ''} on the docket · {replies} "
           f"checked repl{'ies' if replies != 1 else 'y'} · {date} · every finding checked against real tool output",
           17, DIM, "sans", "middle")
    y += 40
    c.line(m, y, W - m, y, INK, 2)
    c.line(m, y + 5, W - m, y + 5, INK, 1)
    y += 26
    c.text(m, y, "FINDINGS", 18, INK, "sans-bold")
    y += 36
    for i, f in enumerate(findings[:MAX_SHOWN], 1):
        colour, label = STAMP[f["verdict"]]
        c.text(m, y, f"Finding {i}.", 22, INK, "serif-bold")
        pill_w = 18 + int(len(label) * 10.5)
        c.rect(m + 132, y - 1, pill_w, 28, colour)
        c.text(m + 132 + pill_w // 2, y + 4, label, 16, "#FFFFFF", "sans-bold", "middle")
        x = m + 132 + pill_w + 16
        lines = wrap(f"“{f['claim']}”", 22, W - m - x, "serif", 2)
        for k, line in enumerate(lines):
            c.text(x, y + k * 28, line, 22, INK, "serif")
        y += 28 * len(lines) + 4
        note = f["cite"] + (" · (recorded, not stamped in chat)" if f["hidden"] else "")
        for line in wrap(note, 16, W - m - (m + 132), "mono", 2):
            c.text(m + 132, y, line, 16, DIM, "mono")
            y += 22
        y += 16
    if len(findings) > MAX_SHOWN:
        c.text(m, y, f"…and {len(findings) - MAX_SHOWN} more finding(s), all counted below · /nocap all lists them",
               17, DIM, "sans")
        y += 34
    if not findings:
        c.text(m, y, "No claims were made in this session, so there is nothing to rule on.", 22, DIM, "serif")
        y += 40
    y += 4
    c.line(m, y, W - m, y, RULE, 2)
    y += 22
    c.text(m, y, "VERDICT", 18, INK, "sans-bold")
    y += 34
    head, colour = ruling(findings)
    c.text(m, y, head, 34, colour, "serif-bold")
    y += 50
    for line in wrap(sentence(findings), 24, W - 2 * m, "serif", 3):
        c.text(m, y, line, 24, INK, "serif")
        y += 32
    y += 18
    c.line(m, y, W - m, y, INK, 1)
    y += 16
    c.text(m, y, "So ordered. No Cap · receipts for agent claims · checked against real tool output · "
           "no extra model, no network", 15, DIM, "sans")
    y += 40
    c.rect(0, y, W, 10, STAMP[CAP][0])
    c.h = y + 10
    return c


def render(records: List[Dict[str, Any]], out_dir: Path,
           session_id: str = "") -> Tuple[List[Path], List[Dict[str, Any]], str]:
    """(paths, findings, caption) for the session (the latest one with receipts when ``session_id`` is empty)."""
    sid, recs = session_records(records, session_id)
    findings = findings_of(recs)
    if not recs or not findings:
        return [], [], ""
    model = model_of(recs)
    canvas = draw(model, sid, findings, len(recs), time.strftime("%Y-%m-%d"))
    return canvas.write(out_dir, "verdict"), findings, f"In re: {model}, session {short_id(sid)}"


def command(records: List[Dict[str, Any]], out_dir: Path, session_id: str = "") -> str:
    paths, findings, caption = render(records, out_dir, session_id)
    if not paths and session_id:  # a fresh session with no checked replies yet: fall back to the latest one
        paths, findings, caption = render(records, out_dir, "")
    if not paths:
        return "⚖️ No receipts in this session yet, so the court has nothing to rule on."
    return (f"⚖️ {caption}\n{ruling(findings)[0]}\n{sentence(findings)}\n🖼️ Verdict card: "
            + " · ".join(str(p) for p in paths))


def remove(out_dir: Path) -> None:
    for name in FILES:
        try:
            (Path(out_dir) / name).unlink()
        except FileNotFoundError:
            pass
