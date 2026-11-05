"""Hermes Desktop receipt chips: the `::nocap{...}` transcript directive and the data behind the Receipts panel.

Desktop renders a paragraph `::nocap{v="2" n="<id>" s="<sig>" d="<base64 json>"}` with No Cap's own component
(TRANSCRIPT_DIRECTIVE_AREA in the Desktop plugin SDK). Every other surface prints that paragraph as raw text, so:

* it is only emitted when the host says the turn's platform is exactly "desktop"
  (tui_gateway/agent_factory.py::_resolve_session_platform, and Desktop's session.create sends source "desktop");
* with `desktop_chips: auto` (default) it is only emitted once the desktop half has said hello through the
  plugin's backend route: Desktop installs a package's desktop half switched OFF, and an unclaimed directive would
  be a raw blob in the chat.

What stops a model from painting its own 🧾 (security review 2-A..2-F):

* every `::nocap` the model wrote is removed from the reply on EVERY surface, after NFKC and with Unicode format
  characters (U+FEFF, zero-width, word joiner…) dropped, repeated until nothing changes (``strip_model_directives``),
  so a replayed or nested directive (``::nocap::nocap{…}``) can't survive into the text Desktop parses;
* the signature is HMAC-SHA256 over (session id, turn id, chip id, payload) with a key that lives only in this
  process's memory, made fresh at every process start and never written to disk or returned by any route;
* the desktop half never sees a key: it asks the backend (``POST /verify``) whether the chip was issued for the chat
  it sits in. The backend answers from the in-memory registry of chips this process issued, or, for chips issued
  before a restart, from the chip id, signature and payload digest recorded in this profile's receipt store.

Limits, stated plainly: this protects against the model's TEXT. A local agent with full shell or file-write access
runs as you and can always read or write your local files (the receipt store included) or attach a debugger to
Hermes; no local plugin can stop that.

Self-contained on purpose (stdlib only, no relative imports at module load): dashboard/desktop_api.py loads this
file by path inside the gateway process. State shared between those module copies lives in one ``sys.modules`` entry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import types
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

NAME = "nocap"
VERSION = "2"
BODY_MAX = 2048          # apps/desktop/src/lib/transcript-directives.ts DIRECTIVE_BODY_MAX
HELLO_FILE = "desktop.json"
LEGACY_KEY_FILE = "desktop.key"  # 0.1 kept the key here; it is deleted on sight
HELLO_MAX_AGE = 30 * 60  # the desktop half re-says hello every 10 minutes while it is loaded
SETTINGS = ("auto", "on", "off")
ORDER = {"CAP": 0, "NO_RECEIPT": 1, "NO_CAP": 2}

# JavaScript's \s (ECMA-262 WhiteSpace + LineTerminator) minus the ASCII ones Python already treats the same way.
# The host's parser sees these as word breaks; they become a plain space.
JS_EXTRA_SPACE = "\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a" \
                 "\u2028\u2029\u202f\u205f\u3000\ufeff"
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
SIG_RE = re.compile(r"^[0-9a-f]{32}$")
D_RE = re.compile(r"^[A-Za-z0-9+/=]{1,4096}$")
MAX_ISSUED = 4096
SHARED = "_no_cap_desktop_process_state"  # one per process, shared by the plugin's and the route's module copies


def is_desktop(platform: Any) -> bool:
    """The only surface that renders the directive. Everything else (cli, tui, gateways, cron, api_server…) gets text."""
    return isinstance(platform, str) and platform.strip().lower() == "desktop"


def setting_of(value: Any) -> str:
    v = str(value if value is not None else "auto").strip().lower()
    return v if v in SETTINGS else "auto"


# ---- the desktop half's hello ---------------------------------------------------------------------------------------
def _private_dir(d: Path) -> None:
    """Created 0700, and tightened to 0700 if it already exists looser (same rule as the receipt store)."""
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass


def _private_write(path: Path, text: str) -> None:
    """Atomic 0600 write: a fresh temp name (random suffix, O_CREAT|O_EXCL|O_NOFOLLOW, so a planted file or symlink
    there makes this fail instead of being followed), then rename over the target (which replaces a symlink at the
    target rather than writing through it)."""
    _private_dir(path.parent)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


# ---- the process key and the chips this process issued ---------------------------------------------------------
def _state() -> Any:
    st = sys.modules.get(SHARED)
    if st is None:
        st = types.ModuleType(SHARED)
        st.key = secrets.token_bytes(32)  # memory only, new every process start
        st.issued = OrderedDict()  # (session_id, chip id) -> {"t": turn_id, "s": sig, "h": sha256(d)}
        st.lock = threading.Lock()
        st = sys.modules.setdefault(SHARED, st)
    return st


def reset_process_state() -> None:
    """Forget the key and the registry, as a process restart would (tests)."""
    sys.modules.pop(SHARED, None)


def process_key() -> bytes:
    return _state().key


def drop_legacy_key(data_dir: Path) -> None:
    """0.1 wrote a signing key to the data folder, where the agent's own file tools could read it. Remove it."""
    try:
        os.unlink(Path(data_dir) / LEGACY_KEY_FILE)
    except OSError:
        pass


def _message(session_id: str, turn_id: str, nonce: str, d: str) -> bytes:
    return json.dumps(["nocap-chip", VERSION, str(session_id), str(turn_id), str(nonce), str(d)],
                      ensure_ascii=True, separators=(",", ":")).encode("ascii")


def sign(key: bytes, session_id: str, turn_id: str, nonce: str, d: str) -> str:
    """HMAC-SHA256 over the session, the turn, the chip id and the payload (first 32 hex chars)."""
    k = key if isinstance(key, bytes) else str(key).encode()
    return hmac.new(k, _message(session_id, turn_id, nonce, d), hashlib.sha256).hexdigest()[:32]


def digest(d: str) -> str:
    return hashlib.sha256(str(d).encode("utf-8")).hexdigest()


def _issue(session_id: str, turn_id: str, d: str) -> Dict[str, str]:
    st = _state()
    nonce = secrets.token_hex(16)
    sig = sign(st.key, session_id, turn_id, nonce, d)
    with st.lock:
        st.issued[(session_id, nonce)] = {"t": turn_id, "s": sig, "h": digest(d)}
        while len(st.issued) > MAX_ISSUED:
            st.issued.popitem(last=False)
    return {"n": nonce, "s": sig, "h": digest(d)}


def verify(session_id: Any, nonce: Any, sig: Any, d: Any,
           records: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Was this chip issued by No Cap for THIS chat? ``session_id`` is the chat the directive is rendered in (the
    Desktop host passes it to the directive component). Answers from this process's registry first (signature
    recomputed with the in-memory key), then from the chip ids recorded in the receipt store (chips from before a
    restart). Never returns a key."""
    no = {"ok": False}
    if not all(isinstance(v, str) for v in (session_id, nonce, sig, d)):
        return dict(no, reason="malformed")
    if not session_id or len(session_id) > 200 or not NONCE_RE.match(nonce) or not SIG_RE.match(sig) \
            or not D_RE.match(d):
        return dict(no, reason="malformed")
    st = _state()
    h = digest(d)
    with st.lock:
        hit = st.issued.get((session_id, nonce))
    if hit is not None:
        want = sign(st.key, session_id, hit["t"], nonce, d)
        if hmac.compare_digest(want, sig) and hmac.compare_digest(hit["s"], sig) and hmac.compare_digest(hit["h"], h):
            return {"ok": True, "session_id": session_id, "turn_id": hit["t"]}
        return dict(no, reason="mismatch")
    for rec in reversed((records() if records else None) or []):
        chip_ids = rec.get("chip") if isinstance(rec, dict) else None
        if not isinstance(chip_ids, dict) or chip_ids.get("n") != nonce:
            continue
        if rec.get("session_id") == session_id and hmac.compare_digest(str(chip_ids.get("s") or ""), sig) \
                and hmac.compare_digest(str(chip_ids.get("h") or ""), h):
            return {"ok": True, "session_id": session_id, "turn_id": str(rec.get("turn_id") or "")}
        return dict(no, reason="mismatch")
    return dict(no, reason="unknown")


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


_PLACEHOLDER = {"n": "0" * 32, "s": "0" * 32}  # same length as the real ids: the budget check is exact


def _render(d: str, ids: Dict[str, str]) -> str:
    return f'::{NAME}{{v="{VERSION}" n="{ids["n"]}" s="{ids["s"]}" d="{d}"}}'


def directive(receipts: List[Dict[str, Any]], session_id: str = "", turn_id: str = "",
              issue: Optional[Callable[[str, str, str], Dict[str, str]]] = None) -> Tuple[str, Dict[str, str]]:
    """The signed directive for these receipts, worst verdict first, inside the host's 2048-char body limit, and the
    chip ids to record with the reply (``{"n", "s", "h"}``). Claims that don't fit are counted in ``more`` (the text
    footer and /nocap still list them)."""
    redact = _redactor()
    ordered = sorted(receipts, key=lambda r: ORDER.get(str(r.get("verdict")), 3))
    base = {"t": _short(turn_id, 24)} if turn_id else {}
    data = dict(base, c=[], more=len(ordered))
    for scale in (1.0, 0.6, 0.35):
        chips: List[Dict[str, Any]] = []
        for r in ordered:
            trial = dict(base, c=chips + [chip(r, scale, redact)], more=len(ordered) - len(chips) - 1)
            if len(_render(_encode(trial), _PLACEHOLDER)) - len(f"::{NAME}{{}}") > BODY_MAX:
                break
            chips.append(chip(r, scale, redact))
        if len(chips) == len(ordered) or (scale == 0.35) or len(chips) >= 6:
            data = dict(base, c=chips, more=len(ordered) - len(chips))
            break
    d = _encode(data)
    ids = (issue or _issue)(session_id, turn_id, d)
    return _render(d, ids), ids


def _normalise(text: str) -> str:
    """What the host could read as a directive: NFKC (so full-width ``：：ｎｏｃａｐ`` is ``::nocap``), Unicode format
    characters (category Cf: U+FEFF, U+200B-U+200F, U+2060…) dropped, and JavaScript-only whitespace made a space."""
    return unicodedata.normalize("NFKC", text).translate(_table())


_TABLE: Dict[int, Optional[str]] = {}


def _table() -> Dict[int, Optional[str]]:
    """str.translate table: every Cf code point (this Python's Unicode data) → removed, JS-only spaces → " ".
    Built once per process (about 0.1 s); after that a 100 KB reply normalises at C speed."""
    if not _TABLE:
        table: Dict[int, Optional[str]] = {cp: None for cp in range(sys.maxunicode + 1)
                                           if unicodedata.category(chr(cp)) == "Cf"}
        table.update({ord(c): " " for c in JS_EXTRA_SPACE})
        _TABLE.update(table)
    return _TABLE


_TOKEN = "::nocap"
_BODY_RE = re.compile(r"\{[^{}]{0,4096}\}")
_DIRECTIVE_RE = re.compile(r"::nocap(?:\{[^{}]{0,4096}\})?", re.IGNORECASE)
_P_RE = re.compile(r"[pP]")
_FAST_PASSES = 8


def _remove_tokens(text: str) -> Tuple[str, int]:
    """Remove ``::nocap`` (any case) and a brace body right after it until nothing changes. A few regex passes
    handle every realistic reply; deeper nesting (``::no::no::nocapcapcap``…) falls back to one linear stack pass
    that drops the token whenever the output ends with it, so a crafted 100 KB reply can't make this quadratic."""
    n = 0
    for _ in range(_FAST_PASSES):
        text, k = _DIRECTIVE_RE.subn("", text)
        n += k
        if not k:
            return text, n
    out: List[str] = []
    i, size = 0, len(text)
    while i < size:
        m = _P_RE.search(text, i)
        j = m.end() if m else size
        out.extend(text[i:j])
        i = j
        if m and len(out) >= 7 and "".join(out[-7:]).lower() == _TOKEN:
            del out[-7:]
            n += 1
            b = _BODY_RE.match(text, i)
            if b:
                i = b.end()
    return "".join(out), n


def strip_model_directives(text: str) -> tuple:
    """Remove every `::nocap` the model wrote itself, on every surface (a replay in a CLI or gateway session is
    otherwise live wherever that transcript is later shown in Desktop). Text without one is returned untouched.
    With one, the reply is normalised (``_normalise``) and every ``::nocap`` (with or without a body) removed to a
    fixed point, so ``::nocap::nocap{…}`` and ``::no::nocapcap{…}`` can't reassemble a directive."""
    if not isinstance(text, str) or _TOKEN not in _normalise(text).lower():
        return text, 0
    cleaned, n = _remove_tokens(_normalise(text))
    cleaned = "\n".join(line.rstrip(" \t") for line in cleaned.split("\n"))  # linear (a `[ \t]+\n` regex isn't)
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
