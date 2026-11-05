"""Hermes Desktop receipt chips: the `::nocap{...}` transcript directive and the data behind the Receipts panel.

Desktop renders a paragraph `::nocap{v="1" s="<sig>" d="<base64 json>"}` with No Cap's own component
(TRANSCRIPT_DIRECTIVE_AREA in the Desktop plugin SDK). Every other surface prints that paragraph as raw text, so:

* it is only emitted when the host says the turn's platform is exactly "desktop"
  (tui_gateway/agent_factory.py::_resolve_session_platform, and Desktop's session.create sends source "desktop");
* with `desktop_chips: auto` (default) it is only emitted once the desktop half has said hello through the
  plugin's backend route: Desktop installs a package's desktop half switched OFF, and an unclaimed directive would
  be a raw blob in the chat;
* it is signed (HMAC-SHA256 with a local key in the plugin's data dir) so a model that copies or invents a
  directive can't paint fake 🧾 chips; the desktop half checks the signature before it draws anything.

Self-contained on purpose (stdlib only, no relative imports at module load): dashboard/plugin_api.py loads this
file by path inside the gateway process.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

NAME = "nocap"
VERSION = "1"
BODY_MAX = 2048          # apps/desktop/src/lib/transcript-directives.ts DIRECTIVE_BODY_MAX
HELLO_FILE = "desktop.json"
KEY_FILE = "desktop.key"
HELLO_MAX_AGE = 30 * 60  # the desktop half re-says hello every 10 minutes while it is loaded
SETTINGS = ("auto", "on", "off")
ORDER = {"CAP": 0, "NO_RECEIPT": 1, "NO_CAP": 2}

# A directive the model wrote: `::nocap` where a word starts, with or without a brace body (host parser rules).
MODEL_DIRECTIVE_RE = re.compile(r"(?<!\S)::nocap(?:\{[^{}\n]{0,4096}\})?")


def is_desktop(platform: Any) -> bool:
    """The only surface that renders the directive. Everything else (cli, tui, gateways, cron, api_server…) gets text."""
    return isinstance(platform, str) and platform.strip().lower() == "desktop"


def setting_of(value: Any) -> str:
    v = str(value if value is not None else "auto").strip().lower()
    return v if v in SETTINGS else "auto"


# ---- the desktop half's hello ---------------------------------------------------------------------------------------
def _private_write(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_hello(data_dir: Path, on: bool, now: Optional[float] = None) -> None:
    _private_write(Path(data_dir) / HELLO_FILE, json.dumps({"on": bool(on), "ts": now if now is not None else time.time()}))


def desktop_live(data_dir: Path, now: Optional[float] = None) -> bool:
    try:
        data = json.loads((Path(data_dir) / HELLO_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("on") is not True:
        return False
    try:
        age = (now if now is not None else time.time()) - float(data.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return -60 <= age <= HELLO_MAX_AGE


def load_key(data_dir: Path) -> str:
    """The local signing key (64 hex chars, 0600). Created on first use; never leaves this machine except to the
    desktop half on the same machine, through the plugin's own backend route."""
    p = Path(data_dir) / KEY_FILE
    try:
        key = p.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{64}", key):
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    _private_write(p, key)
    return key


def sign(key: str, d: str) -> str:
    return hmac.new(key.encode(), d.encode(), hashlib.sha256).hexdigest()[:32]


# ---- the directive --------------------------------------------------------------------------------------------------
def _short(s: Any, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _redactor() -> Callable[[str], str]:
    try:
        from .evidence import redact  # inside the plugin package
        return redact
    except Exception:  # loaded standalone by plugin_api.py: store records are already redacted
        return lambda s: s


def chip(r: Dict[str, Any], n: float = 1.0, redact: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """One receipt as a chip: verdict, the claim's words, the cited call (number, tool, command, exit) and the line
    that proves or contradicts it. ``n`` scales the text budget (1 = full, smaller = tighter)."""
    red = redact or (lambda s: s)
    claim = (r.get("claim") or {}).get("frag") or r.get("text", "")
    out: Dict[str, Any] = {"v": r.get("verdict"), "k": r.get("kind"), "t": red(_short(claim, int(140 * n)))}
    if r.get("cite") is not None:
        out["n"] = r.get("cite")
        if r.get("tool"):
            out["o"] = r.get("tool")
        if r.get("cmd"):
            out["x"] = red(_short(r.get("cmd"), int(120 * n)))
        if r.get("exit") is not None:
            out["e"] = r.get("exit")
    if r.get("quote"):
        out["q"] = red(_short(r.get("quote"), int(160 * n)))
    if r.get("why"):
        out["w"] = red(_short(r.get("why"), int(120 * n)))
    if r.get("verified"):
        out["r"] = red(_short(r.get("verified"), int(100 * n)))
    return out


def _encode(data: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")


def _render(d: str, key: str) -> str:
    return f'::{NAME}{{v="{VERSION}" s="{sign(key, d)}" d="{d}"}}'


def directive(receipts: List[Dict[str, Any]], key: str, turn_id: str = "") -> str:
    """The signed directive for these receipts, worst verdict first, inside the host's 2048-char body limit.
    Claims that don't fit are counted in ``more`` (the text footer and /nocap still list them)."""
    redact = _redactor()
    ordered = sorted(receipts, key=lambda r: ORDER.get(str(r.get("verdict")), 3))
    base = {"t": _short(turn_id, 24)} if turn_id else {}
    for scale in (1.0, 0.6, 0.35):
        chips: List[Dict[str, Any]] = []
        for r in ordered:
            trial = dict(base, c=chips + [chip(r, scale, redact)], more=len(ordered) - len(chips) - 1)
            if len(_render(_encode(trial), key)) - len(f"::{NAME}{{}}") > BODY_MAX:
                break
            chips.append(chip(r, scale, redact))
        if len(chips) == len(ordered) or (scale == 0.35) or len(chips) >= 6:
            data = dict(base, c=chips, more=len(ordered) - len(chips))
            return _render(_encode(data), key)
    return _render(_encode(dict(base, c=[], more=len(ordered))), key)  # pragma: no cover


def strip_model_directives(text: str) -> tuple:
    """Remove every `::nocap` the model wrote itself. Only used where the host replaces the streamed message in
    place (Desktop), so changing the prefix can't make a terminal reprint the reply."""
    n = len(MODEL_DIRECTIVE_RE.findall(text))
    if not n:
        return text, 0
    cleaned = MODEL_DIRECTIVE_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, n


# ---- the Receipts panel --------------------------------------------------------------------------------------------
def session_view(records: List[Dict[str, Any]], session_id: str, limit: int = 50) -> Dict[str, Any]:
    """This session's checked replies (newest first) with their chips, verdict counts and the no-cap streak."""
    counts = {"CAP": 0, "NO_RECEIPT": 0, "NO_CAP": 0}
    if not session_id:
        return {"session_id": "", "replies": [], "counts": counts, "unsure": 0, "streak": 0, "models": []}
    mine = [r for r in records if r.get("session_id") == session_id and r.get("type", "reply") == "reply"
            and r.get("receipts")]
    replies, unsure = [], 0
    for rec in mine:
        every = [x for x in rec.get("receipts") or [] if isinstance(x, dict)]
        shown = [x for x in every if not x.get("hidden")]  # same set the reply was stamped with
        unsure += len(every) - len(shown)
        for x in shown:
            if x.get("verdict") in counts:
                counts[x["verdict"]] += 1
        if not shown:
            continue
        replies.append({"ts": rec.get("ts"), "turn_id": rec.get("turn_id"), "model": rec.get("model"),
                        "calls": (rec.get("ledger") or {}).get("n"),
                        "c": [chip(x) for x in sorted(shown, key=lambda r: ORDER.get(str(r.get("verdict")), 3))]})
    streak = 0
    for rec in reversed(mine):
        if any(x.get("verdict") == "CAP" for x in rec.get("receipts") or []):
            break
        streak += 1
    models = sorted({str(r.get("model") or "unknown") for r in mine})
    return {"session_id": session_id, "replies": list(reversed(replies))[:limit], "counts": counts,
            "unsure": unsure, "streak": streak, "models": models}
