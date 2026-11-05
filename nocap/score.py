"""Cap Score: per-model and per-session honesty record computed from the local receipt store."""
from __future__ import annotations

from typing import Any, Dict, List


def _capped(rec: Dict[str, Any]) -> bool:
    return any(r.get("verdict") == "CAP" for r in rec.get("receipts", []))


def scored(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("receipts") and r.get("type", "reply") == "reply"]


def all_proven(rec: Dict[str, Any]) -> bool:
    """Every receipt the reply was stamped with is 🧾 (hidden 🤔 receipts were never shown, so they don't count)."""
    shown = [x for x in rec.get("receipts") or [] if isinstance(x, dict) and not x.get("hidden")]
    return bool(shown) and all(x.get("verdict") == "NO_CAP" for x in shown)


def streak(records: List[Dict[str, Any]]) -> int:
    """🔥 no cap in a row: all-🧾 replies since the last 🧢. A reply with a 🤔 neither extends nor resets it."""
    n = 0
    for rec in reversed(scored(records)):
        if _capped(rec):
            break
        n += all_proven(rec)
    return n


def table(records: List[Dict[str, Any]], key: str = "model") -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for rec in scored(records):
        groups.setdefault(str(rec.get(key) or "unknown"), []).append(rec)
    rows = []
    for name, recs in groups.items():
        caps = sum(1 for r in recs if _capped(r))
        claims = sum(len(r["receipts"]) for r in recs)
        proven = sum(1 for r in recs for x in r["receipts"] if x.get("verdict") == "NO_CAP")
        unbacked = sum(1 for r in recs for x in r["receipts"] if x.get("verdict") == "NO_RECEIPT")
        rows.append({"name": name, "replies": len(recs), "capped": caps, "rate": caps / len(recs),
                     "claims": claims, "proven": proven, "no_receipt": unbacked, "streak": streak(recs)})
    rows.sort(key=lambda r: (-r["rate"], -r["capped"], r["name"]))
    return rows


def leaderboard_text(records: List[Dict[str, Any]], session_id: str = "") -> str:
    rows = table(records)
    if not rows:
        return "🧾 Cap Score: no checked replies yet. Make a claim, get a receipt."
    lines = ["🧢 **Cap Score** · who caps most"]
    for i, r in enumerate(rows, 1):
        s = f"{r['streak']} replies no cap" if r["streak"] else "streak 0"
        lines.append(f"{i}. {r['name']} · 🧢 {r['capped']}/{r['replies']} replies capped ({r['rate']:.0%}) · "
                     f"🧾 {r['proven']}/{r['claims']} claims proven · 🔥 {s}")
    if session_id:
        mine = [r for r in records if r.get("session_id") == session_id]
        if scored(mine):
            st = streak(mine)
            lines.append(f"This session: 🔥 {st} replies no cap" if st else
                         "This session: streak 0 (only all-🧾 replies count; a 🧢 resets it)")
    lines.append("/capscore card → shareable scorecard image")
    return "\n".join(lines)
