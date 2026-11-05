"""Footer and strict-mode rewrite. Plain lines that read well in a terminal, Discord and Telegram."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .verdict import CAP, NO_CAP, NO_RECEIPT

TAG = {NO_CAP: "🧾 NO CAP", CAP: "🧢 CAP", NO_RECEIPT: "🤔 NO RECEIPT"}
EMOJI = {NO_CAP: "🧾", CAP: "🧢", NO_RECEIPT: "🤔"}
ORDER = {CAP: 0, NO_RECEIPT: 1, NO_CAP: 2}
MAX_LINES = 6


def _short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def claim_text(r: Dict[str, Any]) -> str:
    """The claim's own words: its fragment when one clause held several claims, else the clause."""
    return (r.get("claim") or {}).get("frag") or r.get("text", "")


def receipt_line(r: Dict[str, Any]) -> str:
    claim = f"“{_short(claim_text(r), 60)}”"
    if r["cite"] is not None:
        where = (f"turn {r['turn']} " if r.get("turn") else "") + f"call {r['cite']}"  # cross-turn: an earlier turn
        if r.get("cmd"):
            where += f" `{_short(r['cmd'], 40)}`"
        elif r.get("tool"):
            where += f" {r['tool']}"
        detail = r.get("quote") or r.get("why") or ""
        if r["verdict"] == CAP and detail:
            detail = f"says “{_short(detail, 70)}”"
        elif r["verdict"] == NO_RECEIPT and r.get("why"):
            detail = r["why"]
        tail = f" · {where}" + (f" → {_short(detail, 80)}" if detail else "")
    else:
        tail = f" · {r.get('why') or 'no tool call backs it'}"
    if r.get("verified"):
        tail += f" · ✅ re-checked: {_short(r['verified'], 60)}"
    return f"{TAG[r['verdict']]} {claim}{tail}"


def counts(receipts: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {CAP: 0, NO_RECEIPT: 0, NO_CAP: 0}
    for r in receipts:
        c[r["verdict"]] += 1
    return c


def dedupe(receipts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One sentence holding two claims of one kind, same verdict, same call: show one line."""
    out, seen = [], set()
    for r in receipts:
        sent = (r.get("claim") or {}).get("sent")
        key = (sent, r["kind"], r["verdict"], r.get("cite")) if sent is not None else id(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def footer(receipts: List[Dict[str, Any]], rescore: Optional[List[str]] = None, streak: Optional[int] = None,
           chips: Optional[str] = None) -> str:
    """``chips``: a Desktop `::nocap{...}` directive. It replaces the per-claim lines and stands as its own
    paragraph, because the Desktop host only claims a directive whose paragraph holds nothing else."""
    if not receipts and not rescore:
        return ""
    receipts = dedupe(receipts)
    c = counts(receipts)
    head = ["**Receipts**"]
    for v, word in ((CAP, "cap"), (NO_RECEIPT, "no receipt"), (NO_CAP, "no cap")):
        if c[v]:
            head.append(f"{EMOJI[v]} {c[v]} {word}")
    if streak and not c[CAP]:
        head.append(f"🔥 {streak} no cap in a row")
    lines = [" · ".join(head)]
    for line in rescore or []:
        lines.append(line)
    ordered = sorted(receipts, key=lambda r: ORDER[r["verdict"]])
    if chips and ordered:
        lines.append("\n" + chips + "\n")
    else:
        for r in ordered[:MAX_LINES]:
            lines.append(receipt_line(r))
        if len(ordered) > MAX_LINES:
            lines.append(f"…and {len(ordered) - MAX_LINES} more · /nocap for all")
    if c[CAP] or c[NO_RECEIPT]:
        lines.append("Type /cap and the agent has to show receipts or take it back.")
    return "\n".join(lines)


def unverified_block(receipts: List[Dict[str, Any]]) -> str:
    """Strict mode: the 🧢 claims, restated as unverified. Append-only, so the streamed reply stays intact."""
    caps = [r for r in receipts if r["verdict"] == CAP]
    if not caps:
        return ""
    return "\n".join(["🧢 **Unverified:**"] + [f"Unverified: {_short(claim_text(r), 120)}" for r in caps])


def compose(text: str, receipts: List[Dict[str, Any]], mode: str, rescore: Optional[List[str]] = None,
            streak: Optional[int] = None, notes: Optional[List[str]] = None, plain: bool = False,
            chips: Optional[str] = None) -> Optional[str]:
    """Append-only by design: the classic CLI reprints the whole reply when a rewrite changes its prefix.
    ``plain``: no markdown bold, for surfaces that print the appended footer raw (the classic CLI).
    ``chips``: the Desktop directive (only ever passed for platform "desktop")."""
    if mode == "quiet" or (not receipts and not rescore and not notes):
        return None
    tail = footer(receipts, rescore, streak, chips) if (receipts or rescore) else "**Receipts**"
    if notes:
        tail += "\n" + "\n".join(notes)
    if mode == "strict":
        block = unverified_block(receipts)
        if block:
            tail = block + "\n" + tail
    if plain:
        tail = tail.replace("**", "")
    return text + "\n\n" + tail
