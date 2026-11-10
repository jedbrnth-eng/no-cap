"""Obsidian lessons bridge: No Cap's 🧢 verdicts as per-agent notes in an Obsidian vault, an Agent Black Box board
entry per recurring lesson, and a per-agent "learn from your mistakes" line at the start of each turn.

Opt-in. With `obsidian_vault` empty (the default) nothing here reads or writes anything.

What it writes, only inside the vault the user named (never creates the vault itself):
  <vault>/<obsidian_folder>/<agent>.md   one line per 🧢 CAP verdict for that agent: date, pattern id, the claim and
                                         the contradicting evidence (both redacted, one line, <=160 chars, markdown
                                         escaped) and a block id ^nc-<receipt id> that makes the write idempotent
  <mistakesFolder>/M-NNNN <slug>.md      Agent Black Box's own mistake-note format (agentbox-format 2), ONE per
  <mistakesFolder>/.ids/NNNN             (agent, pattern), created the first time and never edited afterwards; the
                                         id is reserved exactly as ABB does it (exclusive create in .ids)
Every write is confined to the vault: relative folders only, no `..`, no hidden parts, no symlinked folder or note,
O_NOFOLLOW on every open, temp file + os.replace for the agent note, and a lock in No Cap's own data dir.

What it reads back into the prompt: NOTHING from the vault. A vault note is writable by the user, by other tools
and by the agent itself, so prose from it would be an injection path. The lesson line is built from No Cap's local
receipt store (this agent's own 🧢 caps), mapped to the built-in Cap Coach rule text (coach.BY_ID), at most three
rules, labelled, and only when `obsidian_learn: true` as well as `obsidian_vault` is set.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .coach import BY_ID, CAP, classify, mine
from .evidence import redact

DEFAULT_FOLDER = "No Cap"
ABB_CONFIG = ".agentbox.json"
ABB_DATA = "Agent Black Box"
MAX_FIELD = 160
MAX_NOTE_BYTES = 4 * 1024 * 1024
MAX_CONFIG_BYTES = 64 * 1024
LEARN_MIN_CAPS = 2
LEARN_MAX_RULES = 3
LOCK_FILE = "obsidian.lock"
BOARD_MODES = ("auto", "on", "off")
HEADER_SCAN = 4096  # bytes of a board note read to find its source key

_AGENT_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?")
_PART_RE = re.compile(r"[^\x00-\x1f\x7f/\\:*?\"<>|]{1,80}")
_PID_RE = re.compile(r"[a-z_]{1,24}\.[a-z_]{1,32}")
_RID_RE = re.compile(r"[0-9a-f]{12}")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]+")
_MD_RE = re.compile(r"([\\`*_\[\]<>|#^~=$%!{}])")
_SLUG_JUNK_RE = re.compile(r"[^\w\s-]+")
_SPACE_RE = re.compile(r"\s+")
_DASHES_RE = re.compile(r"-{2,}")
_BOARD_NAME_RE = re.compile(r"M-(\d{1,9})\b")
_IDS_NAME_RE = re.compile(r"(\d{1,9})")
_MARK_RE = re.compile(rb"(?m) \^nc-[0-9a-f]{12}\r?$")
_TRUE = ("1", "true", "yes", "on")


# ---- small, pure helpers --------------------------------------------------------------------------------------
def safe_agent(name: Any) -> Optional[str]:
    """A Hermes profile name usable as a file name and as ABB's `agent` field, or None. Rejected, not cleaned up:
    anything with a path separator, `..`, a leading dot, whitespace, control characters or over 64 chars."""
    if not isinstance(name, str):
        return None
    s = name.strip().lower()
    if not s or len(s) > 64 or ".." in s or not _AGENT_RE.fullmatch(s):
        return None
    return s


def safe_folder(rel: Any) -> Optional[List[str]]:
    """A vault-relative folder as its parts, or None: no absolute path, no `~`, no `..`, no hidden part."""
    if not isinstance(rel, str):
        return None
    s = rel.strip().strip("/")
    if not s or rel.strip().startswith(("/", "~", "\\")) or "\\" in s or len(s) > 200:
        return None
    parts = [p for p in s.split("/") if p]
    if not parts or len(parts) > 6:
        return None
    for p in parts:
        if p in (".", "..") or p.startswith(".") or p != p.strip() or not _PART_RE.fullmatch(p):
            return None
    return parts


def one_line(s: Any, n: int = MAX_FIELD) -> str:
    """Control characters and runs of whitespace become one space; cut to n characters with an ellipsis."""
    s = _SPACE_RE.sub(" ", _CTRL_RE.sub(" ", str(s or ""))).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


PRE_REDACT = 2000  # characters kept before redact(): the stored field is 160, so this only bounds the work


def field(s: Any) -> str:
    """A stored field: flattened, bounded, redacted, then cut to MAX_FIELD. When the input is cut before redaction,
    the partial last word is dropped too, so half a secret at the cut can never reach the note."""
    flat = _SPACE_RE.sub(" ", _CTRL_RE.sub(" ", str(s or ""))).strip()
    if len(flat) > PRE_REDACT:
        flat = flat[:PRE_REDACT].rsplit(" ", 1)[0] + " …"
    return one_line(redact(flat), MAX_FIELD)


def escape_md(s: str) -> str:
    """Backslash-escape every character Markdown or Obsidian gives a meaning ([[links]], <html>, #tags, ^block ids,
    %%comments%%, ==highlights==, $math$, embeds, tables), so a claim is shown as text and never as structure."""
    return _MD_RE.sub(r"\\\1", s)


def receipt_id(session_id: Any, turn_id: Any, r: Dict[str, Any]) -> str:
    """Stable per receipt, live and in a backfill: the same fields are on the stored record."""
    claim = (r.get("claim") or {}).get("frag") or r.get("text") or ""
    raw = f"{session_id or ''}|{turn_id or ''}|{r.get('kind') or ''}|{claim}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:12]


def pattern_of(r: Dict[str, Any]) -> str:
    pid = classify(r) or ""
    if pid in BY_ID:
        return pid
    kind = re.sub(r"[^a-z_]", "", str(r.get("kind") or "").lower())[:24] or "claim"
    return f"{kind}.other"


def entry_line(date: str, pid: str, claim: str, evidence: str, rid: str) -> str:
    """One Markdown list line for the agent note. Every field is redacted, flattened and escaped here."""
    pid = pid if _PID_RE.fullmatch(pid or "") else "claim.other"
    rid = rid if _RID_RE.fullmatch(rid or "") else "000000000000"
    date = date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or "") else "0000-00-00"
    c = escape_md(field(claim))
    e = escape_md(field(evidence))
    return f"- {date} 🧢 `{pid}` claim: “{c}” · evidence: “{e}” ^nc-{rid}"


def _date(ts: Any) -> str:
    try:
        t = float(ts)
    except (TypeError, ValueError):
        t = time.time()
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _evidence(r: Dict[str, Any]) -> str:
    return r.get("quote") or r.get("why") or "the tool output in the same turn contradicts it"


def _claim(r: Dict[str, Any]) -> str:
    return (r.get("claim") or {}).get("frag") or r.get("text") or ""


def _slug(title: str) -> str:
    s = _DASHES_RE.sub("-", _SPACE_RE.sub("-", _SLUG_JUNK_RE.sub("", title).strip()))[:50].rstrip("-")
    return s or "mistake"


def lesson_text(records: Iterable[Dict[str, Any]], agent: str, exclude: Iterable[str] = (),
                min_caps: int = LEARN_MIN_CAPS, max_rules: int = LEARN_MAX_RULES) -> Optional[str]:
    """The per-agent lesson line: this agent's own recurring 🧢 patterns (No Cap's local store), mapped to the
    built-in rule text. Never any text from the vault, the store's prose or the agent's replies."""
    who = safe_agent(agent)
    if not who:
        return None
    mine_recs = [r for r in records if isinstance(r, dict) and str(r.get("profile") or "").strip().lower() in ("", who)]
    caps: Dict[str, int] = {}
    for g in mine(mine_recs):
        if g["pattern"] in BY_ID and g.get("caps"):
            caps[g["pattern"]] = caps.get(g["pattern"], 0) + int(g["caps"])
    skip = set(exclude or ())
    top = sorted(((n, p) for p, n in caps.items() if n >= max(1, min_caps) and p not in skip), key=lambda x: (-x[0], x[1]))
    top = top[: max(0, max_rules)]
    if not top:
        return None
    lines = [f"[No Cap lessons for agent {who}: built-in No Cap rules for the 🧢 caps this agent has repeated "
             f"(from No Cap's local receipt store, not from any note). `hermes nocap obsidian status` lists them.]"]
    lines += [f"- {BY_ID[p]['rule']} ({p}, {n}× 🧢)" for n, p in top]
    return "\n".join(lines)


# ---- confined file system access -----------------------------------------------------------------------------
class Refused(ValueError):
    """A path or setting the bridge will not write through. The reason is shown by status and doctor."""


def _within(root: str, path: str) -> bool:
    real = os.path.realpath(path)
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def _dir(root: str, parts: List[str], create: bool = True) -> Path:
    """root/parts..., each part created as needed, none a symlink, the result inside root."""
    d = Path(root)
    for part in parts:
        d = d / part
        try:
            st = os.lstat(d)
        except FileNotFoundError:
            if not create:
                raise Refused(f"{d} does not exist")
            try:
                os.mkdir(d, 0o700)
            except FileExistsError:
                pass
            st = os.lstat(d)
        if stat.S_ISLNK(st.st_mode):
            raise Refused(f"{d} is a symlink; the bridge does not write through links")
        if not stat.S_ISDIR(st.st_mode):
            raise Refused(f"{d} is not a folder")
    if not _within(root, str(d)):
        raise Refused(f"{d} resolves outside the vault")
    return d


def _read_nofollow(path: Path, limit: int) -> Optional[bytes]:
    """The file's bytes (None when it doesn't exist). A symlink, a non-file or a file over `limit` is refused."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise Refused(f"{path} is not a plain file")
    if st.st_size > limit:
        raise Refused(f"{path} is over {limit} bytes")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as fh:
        return fh.read(limit + 1)


def _write_new(path: Path, data: bytes) -> None:
    """Create path exclusively (never through a link); raises FileExistsError when it is there."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _replace(path: Path, data: bytes, mode: int) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.nocap-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def note_header(agent: str) -> bytes:
    return (f"---\ntype: nocap-lessons\nagent: {agent}\n---\n\n# {agent}: claims No Cap stamped 🧢 CAP\n\n"
            "Written by the No Cap plugin: one line per 🧢 CAP verdict (a claim the tool output in the same turn "
            "contradicted), redacted. The lessons this agent is given come from No Cap's own store and built-in "
            "rules, never from this note.\n\n").encode("utf-8")


def board_note(n: int, agent: str, pid: str, date: str, claim: str, evidence: str, log_link: str) -> Tuple[str, str]:
    """(file name, text) of one Agent Black Box mistake note, the same layout ABB's toMarkdown writes."""
    p = BY_ID[pid]
    mid = f"M-{n:04d}"
    title = p["title"][:1].upper() + p["title"][1:]
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - JSON-quoted, as ABB writes it
    what = (f"No Cap stamped 🧢 CAP: the agent claimed “{escape_md(field(claim))}”, and the tool output "
            f"in the same turn said “{escape_md(field(evidence))}”.")
    fm = ["---", f"id: {mid}", f"title: {q(title)}", f"date: {date}", f"agent: {agent}", "severity: high",
          "status: open", f"tags: {q(['nocap', 'cap', p['kind']])}",
          f"related: [{q(log_link)}]", f"source: {q(f'nocap:{agent}:{pid}')}", f"updated: {date}",
          "type: agent-mistake", "agentbox-format: 2", "---", "", f"# {mid} {title}", ""]
    sections = [("What happened", what), ("Impact", ""), ("Cause", p["why"][:1].upper() + p["why"][1:] + "."),
                ("Fix", ""), ("Prevention rule", p["rule"]), ("Verification", ""),
                ("Notes", f"Written once by the No Cap plugin (Obsidian lessons bridge, pattern `{pid}`). Every 🧢 "
                          f"for this agent is listed in [[{log_link}]]. No Cap never edits this note again.")]
    for head, body in sections:
        fm += [f"## {head}"] + ([body] if body else []) + [""]
    fm += ["## Related", f"[[{log_link}]]", ""]
    return f"{mid} {_slug(title)}.md", "\n".join(fm)


# ---- the bridge ------------------------------------------------------------------------------------------------
class Bridge:
    def __init__(self, data_dir: Callable[[], Path], setting: Callable[[str, Any], Any], agent: Callable[[], str]):
        self.data_dir = data_dir
        self.setting = setting
        self.agent = agent
        self._lock = threading.Lock()
        self.last_error = ""

    # -- settings --
    def _get(self, key: str, default: Any) -> Any:
        try:
            v = self.setting(key, default)
        except Exception:
            return default
        return default if v is None else v

    def vault_setting(self) -> str:
        v = self._get("obsidian_vault", "")
        return v.strip() if isinstance(v, str) else ""

    def enabled(self) -> bool:
        return bool(self.vault_setting())

    def learn_on(self) -> bool:
        v = self._get("obsidian_learn", False)
        on = v is True or (isinstance(v, str) and v.strip().lower() in _TRUE)
        return on and self.enabled()

    def folder(self) -> str:
        v = self._get("obsidian_folder", DEFAULT_FOLDER)
        return v if isinstance(v, str) and v.strip() else DEFAULT_FOLDER

    def board_mode(self) -> str:
        v = str(self._get("obsidian_board", "auto") or "auto").strip().lower()
        if v in ("true", "yes", "1"):
            return "on"
        if v in ("false", "no", "0"):
            return "off"
        return v if v in BOARD_MODES else "auto"

    def who(self) -> Optional[str]:
        try:
            return safe_agent(self.agent() or "default")
        except Exception:
            return None

    def vault(self) -> str:
        """The vault's real path. Refused when unset, relative, missing or not a folder (never created)."""
        raw = self.vault_setting()
        if not raw:
            raise Refused("obsidian_vault is not set")
        p = os.path.expanduser(raw)
        if not os.path.isabs(p):
            raise Refused(f"obsidian_vault must be an absolute path, got {raw!r}")
        if not os.path.isdir(p):
            raise Refused(f"vault missing: {p} is not an existing folder (No Cap never creates a vault)")
        return os.path.realpath(p)

    def notes_dir(self, root: str, create: bool = True) -> Path:
        parts = safe_folder(self.folder())
        if parts is None:
            raise Refused(f"obsidian_folder must be a plain vault-relative folder, got {self.folder()!r}")
        return _dir(root, parts, create)

    def board_dir(self, root: str, create: bool = True) -> Optional[Path]:
        """ABB's mistakes folder (from .agentbox.json, else ABB's default), or None when the board is off."""
        mode = self.board_mode()
        if mode == "off":
            return None
        cfg_path = Path(root) / ABB_CONFIG
        raw = _read_nofollow(cfg_path, MAX_CONFIG_BYTES)
        has_abb = raw is not None or os.path.isdir(Path(root) / ABB_DATA)
        if mode == "auto" and not has_abb:
            return None
        cfg: Dict[str, Any] = {}
        if raw is not None:
            try:
                got = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise Refused(f"{ABB_CONFIG} is not valid JSON")
            cfg = got if isinstance(got, dict) else {}
        data = cfg.get("dataFolder") if isinstance(cfg.get("dataFolder"), str) else ABB_DATA
        folder = cfg.get("mistakesFolder") if isinstance(cfg.get("mistakesFolder"), str) else f"{data}/Mistakes"
        parts = safe_folder(folder)
        if parts is None:
            raise Refused(f"{ABB_CONFIG} mistakesFolder is not a plain vault-relative folder: {folder!r}")
        return _dir(root, parts, create)

    # -- writing --
    def _locked(self):
        bridge = self

        class _L:
            def __enter__(self_inner):
                bridge._lock.acquire()
                self_inner.fd = None
                try:
                    d = Path(bridge.data_dir())
                    d.mkdir(mode=0o700, parents=True, exist_ok=True)
                    self_inner.fd = os.open(d / LOCK_FILE, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                    fcntl.flock(self_inner.fd, fcntl.LOCK_EX)
                except OSError:
                    self_inner.fd = None  # no cross-process lock: the thread lock still serialises this process
                return self_inner

            def __exit__(self_inner, *exc):
                if self_inner.fd is not None:
                    try:
                        fcntl.flock(self_inner.fd, fcntl.LOCK_UN)
                    finally:
                        os.close(self_inner.fd)
                bridge._lock.release()
                return False
        return _L()

    def record(self, receipts: List[Dict[str, Any]], session_id: str = "", turn_id: str = "",
               ts: Optional[float] = None, agent: Optional[str] = None) -> Dict[str, Any]:
        """Append one line per 🧢 in `receipts` to the agent's note, and the first board note per pattern."""
        out: Dict[str, Any] = {"written": 0, "board": [], "skipped": ""}
        caps = [r for r in receipts or [] if isinstance(r, dict) and r.get("verdict") == CAP]
        if not caps or not self.enabled():
            out["skipped"] = "off" if not self.enabled() else ""
            return out
        who = safe_agent(agent) if agent is not None else self.who()
        if not who:
            out["skipped"] = "agent name refused"
            self.last_error = "agent name refused (letters, digits, . _ - only)"
            return out
        try:
            root = self.vault()
            with self._locked():
                notes = self.notes_dir(root)
                path = notes / f"{who}.md"
                old = _read_nofollow(path, MAX_NOTE_BYTES)
                buf = old if old is not None else note_header(who)
                date = _date(ts if ts is not None else time.time())
                firsts: Dict[str, Dict[str, Any]] = {}
                for r in caps:
                    rid = receipt_id(session_id, turn_id, r)
                    pid = pattern_of(r)
                    if pid in BY_ID:
                        firsts.setdefault(pid, r)
                    if re.search(rb"(?m) \^nc-" + rid.encode() + rb"\r?$", buf):
                        continue
                    if buf and not buf.endswith(b"\n"):
                        buf += b"\n"
                    buf += (entry_line(date, pid, _claim(r), _evidence(r), rid) + "\n").encode("utf-8", "replace")
                    out["written"] += 1
                if out["written"]:
                    mode = (os.lstat(path).st_mode & 0o777) if old is not None else 0o600
                    _replace(path, buf, mode)
                link = "/".join(safe_folder(self.folder()) or [DEFAULT_FOLDER]) + f"/{who}"
                for pid, r in firsts.items():
                    try:
                        made = self._board(root, who, pid, date, r, link)
                    except (Refused, OSError) as exc:
                        self.last_error = f"board: {exc}"
                        continue
                    if made:
                        out["board"].append(made)
        except Refused as exc:
            out["skipped"] = str(exc)
            self.last_error = str(exc)
        return out

    def _board(self, root: str, who: str, pid: str, date: str, r: Dict[str, Any], link: str) -> Optional[str]:
        d = self.board_dir(root)
        if d is None:
            return None
        src = f'source: "nocap:{who}:{pid}"'.encode()
        top = 0
        for entry in os.scandir(d):
            m = _BOARD_NAME_RE.match(entry.name)
            if m:
                top = max(top, int(m.group(1)))
            if not entry.name.endswith(".md") or not entry.is_file(follow_symlinks=False):
                continue
            try:
                fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as fh:
                    head = fh.read(HEADER_SCAN)
            except OSError:
                continue
            if src in head.split(b"\n---", 1)[0]:
                return None  # this lesson is on the board already (ours, or claimed by hand: never duplicated)
        ids = d / ".ids"
        try:
            os.mkdir(ids, 0o700)
        except FileExistsError:
            pass
        st = os.lstat(ids)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or not _within(root, str(ids)):
            raise Refused(f"{ids} is not a plain folder")
        for entry in os.scandir(ids):
            m = _IDS_NAME_RE.fullmatch(entry.name)
            if m:
                top = max(top, int(m.group(1)))
        n = top + 1
        for _ in range(100):
            try:
                _write_new(ids / f"{n:04d}", b"")
            except FileExistsError:
                n += 1
                continue
            name, text = board_note(n, who, pid, date, _claim(r), _evidence(r), link)
            try:
                _write_new(d / name, text.encode("utf-8"))
            except FileExistsError:
                n += 1
                continue
            return name
        raise Refused("could not reserve a board id after 100 tries")

    def sync(self, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Backfill from the local store: every stored 🧢, idempotent per receipt id."""
        total: Dict[str, Any] = {"written": 0, "board": [], "skipped": ""}
        for rec in records:
            if not isinstance(rec, dict) or rec.get("type", "reply") != "reply" or not rec.get("receipts"):
                continue
            if not any(isinstance(x, dict) and x.get("verdict") == CAP for x in rec["receipts"]):
                continue
            agent = safe_agent(rec.get("profile")) or self.who()
            got = self.record(rec["receipts"], str(rec.get("session_id") or ""), str(rec.get("turn_id") or ""),
                              ts=rec.get("ts"), agent=agent or "")
            total["written"] += got["written"]
            total["board"] += got["board"]
            if got["skipped"] and got["skipped"] != "off":
                total["skipped"] = got["skipped"]
        return total

    # -- learning --
    def lessons(self, records: Iterable[Dict[str, Any]], exclude: Iterable[str] = ()) -> Optional[str]:
        if not self.learn_on():
            return None
        who = self.who()
        if not who:
            return None
        return lesson_text(records, who, exclude)

    # -- reporting --
    def counts(self, root: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        try:
            d = self.notes_dir(root, create=False)
        except Refused:
            return out
        for entry in sorted(os.scandir(d), key=lambda e: e.name):
            if not entry.name.endswith(".md") or not entry.is_file(follow_symlinks=False):
                continue
            who = safe_agent(entry.name[:-3])
            if not who:
                continue
            try:
                data = _read_nofollow(Path(entry.path), MAX_NOTE_BYTES) or b""
            except (Refused, OSError):
                continue
            out[who] = len(_MARK_RE.findall(data))
        return out

    def board_count(self, root: str) -> int:
        try:
            d = self.board_dir(root, create=False)
        except (Refused, OSError):
            return 0
        if d is None:
            return 0
        n = 0
        for entry in os.scandir(d):
            if entry.name.endswith(".md") and entry.is_file(follow_symlinks=False):
                try:
                    fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, "rb") as fh:
                        n += b'source: "nocap:' in fh.read(HEADER_SCAN)
                except OSError:
                    continue
        return n

    def status(self, records: Iterable[Dict[str, Any]] = ()) -> str:
        if not self.enabled():
            return ("📓 Obsidian lessons: off. Set plugins.entries.no-cap.settings.obsidian_vault to a vault folder to "
                    "turn it on (docs/OBSIDIAN.md). Nothing is read or written while it is off.")
        lines = ["📓 Obsidian lessons: on"]
        try:
            root = self.vault()
        except Refused as exc:
            return "\n".join(lines + [f"❌ {exc}"])
        who = self.who() or "(refused name)"
        lines.append(f"vault: {root}")
        try:
            lines.append(f"notes: {self.notes_dir(root, create=False)}/<agent>.md · this agent: {who}")
        except Refused as exc:
            lines.append(f"notes: {self.folder()}/ not created yet ({exc})")
        try:
            b = self.board_dir(root, create=False)
            lines.append(f"Agent Black Box board: {self.board_mode()} → " + (f"{b} · {self.board_count(root)} lesson "
                         f"note(s) by No Cap" if b else "not used (no .agentbox.json or Agent Black Box folder)"))
        except (Refused, OSError) as exc:
            lines.append(f"Agent Black Box board: {self.board_mode()} → refused: {exc}")
        counts = self.counts(root)
        lines.append("🧢 per agent: " + (" · ".join(f"{a}: {n}" for a, n in counts.items()) or "none yet"))
        if self.learn_on():
            text = lesson_text(list(records), who)
            lines.append("learn: on (a pattern with 2+ 🧢 becomes a built-in rule line, max 3, in pre_llm_call)")
            lines.append("next turn for this agent: " + ("; ".join(l[2:] for l in text.splitlines()[1:]) if text
                                                         else "no lesson yet"))
        else:
            lines.append("learn: off (obsidian_learn: true turns on the per-agent lesson line)")
        if self.last_error:
            lines.append(f"last refusal: {self.last_error}")
        return "\n".join(lines)

    def doctor_line(self) -> Tuple[str, bool]:
        if not self.enabled():
            return "ℹ️ Obsidian lessons: off (obsidian_vault not set).", False
        try:
            root = self.vault()
        except Refused as exc:
            return f"❌ Obsidian lessons: {exc}.", True
        if not self.who():
            return "❌ Obsidian lessons: this profile's name can't be a note name (letters, digits, . _ - only).", True
        if safe_folder(self.folder()) is None:
            return f"❌ Obsidian lessons: obsidian_folder {self.folder()!r} is not a plain vault-relative folder.", True
        board = self.board_mode()
        return (f"✅ Obsidian lessons: on · {root} · notes in {self.folder()}/ · ABB board {board} · learn "
                f"{'on' if self.learn_on() else 'off'}"), False

    def open_text(self) -> str:
        try:
            root = self.vault()
        except Refused as exc:
            return f"📓 {exc}"
        who = self.who()
        parts = safe_folder(self.folder())
        if not who or parts is None:
            return "📓 The agent name or obsidian_folder is refused; see `hermes nocap obsidian status`."
        path = Path(root, *parts, f"{who}.md")
        uri = "obsidian://open?path=" + urllib.parse.quote(str(path), safe="")
        note = "" if path.exists() else " (no 🧢 recorded for this agent yet, so the note doesn't exist)"
        return f"📓 {path}{note}\nOpen in Obsidian: {uri}"

    def command(self, action: str, records: List[Dict[str, Any]]) -> str:
        action = (action or "status").strip().lower()
        if action == "open":
            return self.open_text()
        if action == "sync":
            if not self.enabled():
                return self.status()
            got = self.sync(records)
            msg = (f"📓 Synced from the local store: {got['written']} new 🧢 line(s), "
                   f"{len(got['board'])} new Agent Black Box lesson note(s).")
            return msg + (f" Refused: {got['skipped']}" if got["skipped"] else "")
        return self.status(records)


__all__ = ["Bridge", "Refused", "safe_agent", "safe_folder", "entry_line", "receipt_id", "lesson_text",
           "escape_md", "board_note"]
