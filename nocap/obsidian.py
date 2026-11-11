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
the vault held by one descriptor opened component by component with O_NOFOLLOW (an ancestor swapped for a symlink
is refused), every later open relative to it, temp file + os.replace for the agent note, and an flock on the
destination folder itself, so two Hermes homes writing into one vault serialize. An unknown profile writes nothing.

What it reads back into the prompt: NOTHING from the vault. A vault note is writable by the user, by other tools
and by the agent itself, so prose from it would be an injection path. The lesson line is built from No Cap's local
receipt store (this agent's own 🧢 caps), mapped to the built-in Cap Coach rule text (coach.BY_ID), at most three
rules, labelled, and only when `obsidian_learn: true` as well as `obsidian_vault` is set.
"""
from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows can still use No Cap while this optional bridge is off.
    fcntl = None
import hashlib
from contextlib import contextmanager
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
BOARD_MODES = ("auto", "on", "off")
HEADER_SCAN = 4096  # bytes of a board note read to find its source key
BOARD_OPEN_MAX = 32  # board notes opened per cap write (only those named like the pattern)
LOCK_BUDGET = 0.12  # seconds one record() call may wait for destination locks IN ALL (both folders, the retries)
LOCK_PAUSE = (0.002, 0.004, 0.008, 0.016, 0.032)  # pauses between non-blocking lock tries
PENDING_MAX = 64  # exports skipped on a busy folder, kept in memory for the next write (sync covers the rest)
PENDING_FLUSH = 4  # skipped exports retried per write, so one turn's work stays bounded
LESSONS_FILE = "obsidian-lessons.json"  # per-agent 🧢 pattern counts (ids and numbers only), in the plugin data dir
LEARN_CPU = 0.015  # seconds of CPU one pre_llm_call may spend catching the cache up with the store
LEARN_BLOCK = 256 * 1024  # store bytes read per step while catching up
LEARN_MAX_READ = 8 * 1024 * 1024  # store bytes read per pre_llm_call at most, whatever the CPU clock says
LEARN_TAIL = 64  # bytes before the cached offset re-hashed each turn: a store rewritten in place is rebuilt
LEARN_HEAD = 256  # and the store's first bytes (a rewrite often keeps the line ends the same)
MAX_CACHE_BYTES = 256 * 1024
MAX_CACHE_AGENTS = 256
SCAN_DIR_BYTES = 64 * 1024  # a board folder is listed (once, on its first write) only when its size is this or less
SCAN_MAX = 4096  # and then at most this many names
INDEX_OPEN_MAX = 128  # board notes opened in all when an index is seeded (BOARD_OPEN_MAX for the current pattern)
MAX_INDEX_KEYS = 4096
ID_TRIES = 32  # exclusive creates per board write; each miss re-probes with _free_id

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
    if not s or len(s) > 64 or ".." in s or not _AGENT_RE.fullmatch(s) or redact(name) != name:
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
        if (p in (".", "..") or p.startswith(".") or p != p.strip() or not _PART_RE.fullmatch(p)
                or any(c in p for c in "[]#^%{}=!$~`") or redact(p) != p):
            return None
    return parts


def one_line(s: Any, n: int = MAX_FIELD) -> str:
    """Control characters and runs of whitespace become one space; cut to n characters with an ellipsis."""
    s = _SPACE_RE.sub(" ", _CTRL_RE.sub(" ", str(s or ""))).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def field(s: Any) -> str:
    """Redact the COMPLETE field before flattening or clipping it. A mask may need distant context (the @ after
    a long URL password, a PEM end marker, a closing quote); a pre-redaction window could expose the kept prefix."""
    return one_line(redact(str(s or "")), MAX_FIELD)


def escape_md(s: str) -> str:
    """Backslash-escape every character Markdown or Obsidian gives a meaning ([[links]], <html>, #tags, ^block ids,
    %%comments%%, ==highlights==, $math$, embeds, tables), so a claim is shown as text and never as structure."""
    return _MD_RE.sub(r"\\\1", s)


def receipt_id(session_id: Any, turn_id: Any, r: Dict[str, Any]) -> str:
    """Stable per receipt, live and in a backfill: the same fields are on the stored record."""
    claim = (r.get("claim") or {}).get("frag") or r.get("text") or ""
    raw = f"{session_id or ''}|{turn_id or ''}|{r.get('kind') or ''}|{redact(str(claim))}"
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
    return redact(f"- {date} 🧢 `{pid}` claim: “{c}” · evidence: “{e}” ^nc-{rid}")


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
    mine_recs = [r for r in records if isinstance(r, dict) and str(r.get("profile") or "").strip().lower() == who]
    caps: Dict[str, int] = {}
    for g in mine(mine_recs):
        if g["pattern"] in BY_ID and g.get("caps"):
            caps[g["pattern"]] = caps.get(g["pattern"], 0) + int(g["caps"])
    return lesson_from_counts(caps, who, exclude, min_caps, max_rules)


def capped_patterns(rec: Any) -> Tuple[str, List[str]]:
    """(agent key, the patterns this ONE stored record adds a 🧢 to), exactly as coach.mine counts it for
    lesson_text: replies with receipts only, one count per pattern per reply, decided by the first receipt of that
    pattern. Counts add up across records, so the lessons cache can be built one appended line at a time."""
    if not isinstance(rec, dict) or rec.get("type", "reply") != "reply" or not rec.get("receipts"):
        return "", []
    try:
        if float(rec.get("ts", 0) or 0) < 0:
            return "", []
    except (TypeError, ValueError):
        return "", []
    who = str(rec.get("profile") or "").strip().lower()
    if not who or safe_agent(who) != who or not isinstance(rec["receipts"], list):
        return "", []
    seen, out = set(), []
    for x in rec["receipts"]:
        if not isinstance(x, dict):
            continue
        pid = classify(x)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        if pid in BY_ID and x.get("verdict") == CAP:
            out.append(pid)
    return who, out


def lesson_from_counts(caps: Dict[str, int], who: str, exclude: Iterable[str] = (),
                       min_caps: int = LEARN_MIN_CAPS, max_rules: int = LEARN_MAX_RULES) -> Optional[str]:
    caps = {p: int(n) for p, n in (caps or {}).items() if p in BY_ID and isinstance(n, int) and n > 0}
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


@contextmanager
def _vault_fd(real: str):
    """The resolved vault held by one descriptor, opened ONE component at a time from `/` with O_NOFOLLOW. `real` is
    a realpath, so it has no symlink in it: if any ancestor was swapped for a symlink after it was resolved, an open
    fails and the write is refused, instead of following the swap out of the vault. Every later open is relative to
    this descriptor. (A symlink the user configured in obsidian_vault itself was resolved by vault() and is used.)"""
    if not os.path.isabs(real):
        raise Refused(f"vault path {real!r} is not absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(real).parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise Refused(f"vault path changed while opening it (at {part!r}: {exc.strerror}); not written")
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    try:
        yield fd
    finally:
        os.close(fd)


class Busy(Refused):
    """The destination folder is locked by another writer: this optional export is skipped, never waited for."""


@contextmanager
def _flock(fd: int, deadline: Optional[float] = None):
    """Exclusive lock on a pinned destination folder, shared by every Hermes home and thread writing into it (an
    flock on its own open file description). Never blocks: non-blocking tries with short pauses until `deadline`
    (time.monotonic(); one record() call shares LOCK_BUDGET across all its locks), then Busy: the export is skipped
    and picked up later, the reply is never held. Fails closed: no lock, no write."""
    if fcntl is None:
        raise Refused("Obsidian writes require POSIX directory handles and flock")
    if deadline is None:
        deadline = time.monotonic() + LOCK_BUDGET
    k = 0
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (BlockingIOError, InterruptedError):
            pause = LOCK_PAUSE[min(k, len(LOCK_PAUSE) - 1)]
            k += 1
            if time.monotonic() + pause > deadline:
                raise Busy("destination folder busy (another writer holds its lock); export skipped, not waited "
                           "for: the next write or `hermes nocap obsidian sync` picks it up")
            time.sleep(pause)
    try:
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _pinned_dir(base_fd: int, parts: List[str], create: bool = True, idents: Optional[List[Tuple[int, int]]] = None):
    """Pin each directory with openat(O_NOFOLLOW) below the held vault descriptor. A concurrent rename or symlink
    swap cannot redirect a write: all later operations use the pinned directory fd, never an absolute path. The
    (st_dev, st_ino) of each pinned folder is appended to `idents`, for _verify before the final write."""
    fd = os.dup(base_fd)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            if idents is not None:
                idents.append(_ident(fd))
        yield fd
    finally:
        os.close(fd)


def _ident(fd: int) -> Tuple[int, int]:
    st = os.fstat(fd)
    return st.st_dev, st.st_ino


def _verify(root: str, parts: List[str], idents: List[Tuple[int, int]]) -> None:
    """Review 2 (R2): the held descriptors pin inodes, not their place in the tree. A pinned folder (or the vault)
    moved OUT of the vault and replaced by a symlink would still take the write. So, right before a write commits,
    walk the path again from `/` with O_NOFOLLOW and compare st_dev/st_ino of the vault (idents[0]) and of each
    pinned folder below it (idents[1:]). Any difference, a symlink or a missing part: Refused, nothing written.
    The re-check and the write are two system calls: a move in the microseconds between them is not caught."""
    names = list(Path(root).parts[1:])
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for i, part in enumerate(names + list(parts)):
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                raise Refused(f"destination moved out of the vault after it was opened (at {part!r}: "
                              f"{exc.strerror}); not written")
            os.close(fd)
            fd = child
            k = i - len(names) + 1  # 0 = the vault itself, 1.. = the folders below it
            if k >= 0 and (k >= len(idents) or _ident(fd) != idents[k]):
                raise Refused(f"destination moved out of the vault after it was opened (at {part!r}: not the "
                              "folder that was opened); not written")
    finally:
        os.close(fd)


def _read_nofollow(path: Path, limit: int, dir_fd: Optional[int] = None) -> Optional[bytes]:
    """The file's bytes (None when it doesn't exist). A symlink, a non-file or a file over `limit` is refused."""
    try:
        st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise Refused(f"{path} is not a plain file")
    if st.st_size > limit:
        raise Refused(f"{path} is over {limit} bytes")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise Refused(f"{path} is not a plain file")
        return fh.read(limit + 1)


def _write_new(path: Path, data: bytes, dir_fd: Optional[int] = None,
               check: Optional[Callable[[], None]] = None) -> None:
    """Create path exclusively (never through a link); raises FileExistsError when it is there. `check` (_verify)
    runs right before the create."""
    if check is not None:
        check()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except BaseException:
        try:
            os.unlink(path, dir_fd=dir_fd)
        except OSError:
            pass
        raise


def _replace(path: Path, data: bytes, mode: int, dir_fd: Optional[int] = None,
             check: Optional[Callable[[], None]] = None) -> None:
    """Temp file + fsync + os.replace in the pinned folder. `check` (_verify) runs before the temp file is created
    and again right before the replace; a failed check removes the temp file and writes nothing."""
    if check is not None:
        check()
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.nocap-tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if check is not None:
            check()
        os.replace(tmp, path, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except OSError:
            pass
        raise


def _title(pid: str) -> str:
    t = BY_ID[pid]["title"]
    return t[:1].upper() + t[1:]


def note_header(agent: str) -> bytes:
    # agent JSON-quoted: a profile named 123, null or true stays a string in YAML (and in ABB's unquote)
    return redact(f"---\ntype: nocap-lessons\nagent: {json.dumps(agent)}\n---\n\n# {agent}: claims No Cap stamped 🧢 CAP\n\n"
            "Written by the No Cap plugin: one line per 🧢 CAP verdict (a claim the tool output in the same turn "
            "contradicted), redacted. The lessons this agent is given come from No Cap's own store and built-in "
            "rules, never from this note.\n\n").encode("utf-8")


def board_note(n: int, agent: str, pid: str, date: str, claim: str, evidence: str, log_link: str) -> Tuple[str, str]:
    """(file name, text) of one Agent Black Box mistake note, the same layout ABB's toMarkdown writes."""
    p = BY_ID[pid]
    mid = f"M-{n:04d}"
    title = _title(pid)
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - JSON-quoted, as ABB writes it
    what = (f"No Cap stamped 🧢 CAP: the agent claimed “{escape_md(field(claim))}”, and the tool output "
            f"in the same turn said “{escape_md(field(evidence))}”.")
    fm = ["---", f"id: {mid}", f"title: {q(title)}", f"date: {date}", f"agent: {q(agent)}", "severity: high",
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
    return f"{mid} {_slug(title)}.md", redact("\n".join(fm))


# ---- the lessons cache (review 2, R3) ----------------------------------------------------------------------------
def _cpu() -> float:
    try:
        return time.thread_time()
    except (AttributeError, OSError):  # pragma: no cover - platforms without a per-thread clock
        return time.process_time()


def _load_cache(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = _read_nofollow(path, MAX_CACHE_BYTES)
        got = json.loads(raw.decode("utf-8")) if raw else None
    except (Refused, OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(got, dict) or got.get("v") != 1:
        return None
    try:
        out = {"v": 1, "dev": int(got["dev"]), "ino": int(got["ino"]), "offset": int(got["offset"]),
               "tailh": str(got["tailh"]), "headh": str(got["headh"]), "tail": b"", "done": bool(got["done"]),
               "counts": _clean_counts(got["counts"]), "prev": _clean_counts(got["prev"]) if got.get("prev") else None}
    except (KeyError, TypeError, ValueError):
        return None
    return out if out["offset"] >= 0 else None


def _clean_counts(c: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(c, dict):
        raise ValueError("counts")
    out: Dict[str, Dict[str, int]] = {}
    for who, pats in list(c.items())[:MAX_CACHE_AGENTS]:
        if isinstance(who, str) and safe_agent(who) == who and isinstance(pats, dict):
            out[who] = {p: int(n) for p, n in pats.items() if p in BY_ID and isinstance(n, int) and n > 0}
    return out


def _save_cache(path: Path, c: Dict[str, Any]) -> None:
    """0600, temp file + os.replace in the plugin's own data folder. Agent names, pattern ids and counts only."""
    body = json.dumps({"v": 1, "dev": c["dev"], "ino": c["ino"], "offset": c["offset"], "tailh": _tail_hash(c["tail"]),
                       "headh": c["headh"],
                       "done": c["done"], "counts": c["counts"], "prev": c["prev"]}, sort_keys=True).encode()
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _tail_hash(b: bytes) -> str:
    """A digest of the last LEARN_TAIL store bytes before the offset: detects a store rewritten in place without
    keeping any of its text in the cache."""
    return hashlib.sha256(b).hexdigest()[:32]


def _tally(block: bytes, counts: Dict[str, Dict[str, int]]) -> None:
    for line in block.split(b"\n"):
        if b'"CAP"' not in line:  # a record without a 🧢 receipt adds nothing: no parse
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        who, pids = capped_patterns(rec)
        if not pids or (who not in counts and len(counts) >= MAX_CACHE_AGENTS):
            continue
        mine_ = counts.setdefault(who, {})
        for pid in pids:
            mine_[pid] = mine_.get(pid, 0) + 1


def lesson_counts(store: Path, cache: Path) -> Dict[str, Dict[str, int]]:
    """Per-agent 🧢 pattern counts of the receipt store, from a small cache that is caught up with what was
    appended since the last call, under a CPU budget (LEARN_CPU) and a read cap (LEARN_MAX_READ). The store is
    never parsed whole in one call: a new, replaced, truncated or rewritten store is rebuilt over the next calls,
    showing the last complete counts meanwhile (or the partial counts, which only grow, when there are none)."""
    c = _load_cache(cache)
    try:
        fh = open(store, "rb")
    except FileNotFoundError:  # purged: the caps went with it
        if c is not None:
            try:
                os.unlink(cache)
            except OSError:
                pass
        return {}
    with fh:
        st = os.fstat(fh.fileno())
        stale = c is None or (c["dev"], c["ino"]) != (st.st_dev, st.st_ino) or st.st_size < c["offset"]
        if not stale and c["offset"]:
            n = min(LEARN_TAIL, c["offset"])
            fh.seek(c["offset"] - n)
            c["tail"] = fh.read(n)
            fh.seek(0)
            stale = (_tail_hash(c["tail"]) != c["tailh"]
                     or _tail_hash(fh.read(min(LEARN_HEAD, c["offset"]))) != c["headh"])
        if stale:
            prev = (c["counts"] if c["done"] else c["prev"]) if c else None
            c = {"v": 1, "dev": st.st_dev, "ino": st.st_ino, "offset": 0, "tail": b"", "tailh": "", "headh": "",
                 "done": False, "counts": {}, "prev": prev or None}
        changed = stale
        if c["offset"] < st.st_size:
            fh.seek(c["offset"])
            start, read, rest, eof = _cpu(), 0, b"", False
            while True:
                block = fh.read(LEARN_BLOCK)
                if not block:
                    eof = True
                    break
                read += len(block)
                data = rest + block
                cut = data.rfind(b"\n") + 1
                if cut:
                    _tally(data[:cut], c["counts"])
                    c["tail"] = (c["tail"] + data[:cut])[-LEARN_TAIL:]
                    c["offset"] += cut
                    changed = True
                rest = data[cut:]
                if _cpu() - start > LEARN_CPU or read >= LEARN_MAX_READ:
                    break
            if eof and not c["done"]:
                c["done"], c["prev"], changed = True, None, True
        elif not c["done"]:
            c["done"], c["prev"], changed = True, None, True
        if changed:
            fh.seek(0)
            c["headh"] = _tail_hash(fh.read(min(LEARN_HEAD, c["offset"])))
            try:
                _save_cache(cache, c)
            except OSError:
                pass  # the cache is an optimisation: next turn catches up from the last saved point
    return c["counts"] if c["done"] or not c["prev"] else c["prev"]


# ---- the board index (review 2, R4) ------------------------------------------------------------------------------
def _id_taken(ids_fd: int, n: int) -> bool:
    try:
        os.stat(f"{n:04d}", dir_fd=ids_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _free_id(ids_fd: int, n: int) -> int:
    """The first id from n on that has no .ids reservation, by galloping then bisecting stat probes: about
    2*log2(k) probes to skip k taken ids. Reservations are dense (ABB and No Cap never delete them); a gap below the
    newest id can be found first, which is still a free id. The exclusive create after this is the real guard."""
    if not _id_taken(ids_fd, n):
        return n
    lo, step = n, 1
    while _id_taken(ids_fd, n + step):
        lo = n + step
        step *= 2
        if step > 1 << 30:
            raise Refused("no free board id found")
    hi = n + step
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _id_taken(ids_fd, mid):
            lo = mid
        else:
            hi = mid
    return hi


def _load_index(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = _read_nofollow(path, MAX_CACHE_BYTES)
        got = json.loads(raw.decode("utf-8")) if raw else None
    except (Refused, OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(got, dict) or got.get("v") != 1 or not isinstance(got.get("keys"), dict):
        return None
    try:
        nxt = int(got.get("next") or 1)
    except (TypeError, ValueError):
        return None
    keys = {k: v for k, v in list(got["keys"].items())[:MAX_INDEX_KEYS]
            if isinstance(k, str) and isinstance(v, str) and _BOARD_NAME_RE.match(v) and "/" not in v
            and not v.startswith(".")}
    return {"v": 1, "next": max(1, nxt), "keys": keys}


def _save_index(path: Path, idx: Dict[str, Any]) -> None:
    """0600 in the plugin data dir: agent:pattern -> note file name, and the next id hint. No claim text."""
    try:
        os.makedirs(path.parent, mode=0o700, exist_ok=True)
        body = json.dumps({"v": 1, "next": idx["next"], "keys": idx["keys"]}, sort_keys=True).encode()
        tmp = path.with_name(f".{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass  # the index is an optimisation: without it the next write seeds again (bounded)


def _small_names(dir_fd: int, st: os.stat_result) -> Optional[List[str]]:
    """The folder's names when it is small (SCAN_DIR_BYTES, SCAN_MAX names), else None, so a listing never grows
    with the board. A folder whose size says nothing (some file systems report 0) is still cut at SCAN_MAX."""
    if st.st_size > SCAN_DIR_BYTES:
        return None
    names: List[str] = []
    for entry in os.scandir(dir_fd):
        names.append(entry.name)
        if len(names) > SCAN_MAX:
            return None
    return names


_SLUG_PID = {f" {_slug(_title(p))}.md": p for p in BY_ID}


def _seed_index(board_fd: int, st: os.stat_result, pid: str) -> Dict[str, Any]:
    """First write to a board with no index here. A small board is listed once: the highest M-NNNN and .ids number
    give the next id, and notes named like a pattern's title (`M-NNNN <slug>.md`, at most BOARD_OPEN_MAX for the
    current pattern and INDEX_OPEN_MAX in all) are opened for their `source: "nocap:<agent>:<pattern>"` key. A big
    board is not listed: the id comes from _free_id's probes and only notes this index records are known."""
    idx: Dict[str, Any] = {"v": 1, "next": 1, "keys": {}}
    names = _small_names(board_fd, st)
    if names is None:
        return idx
    top = 0
    cands: List[Tuple[str, str]] = []
    for name in names:
        m = _BOARD_NAME_RE.match(name)
        if not m:
            continue
        top = max(top, int(m.group(1)))
        tail = name[name.find(" "):] if " " in name else ""
        if tail in _SLUG_PID:
            cands.append((_SLUG_PID[tail], name))
    if sum(1 for p, _ in cands if p == pid) > BOARD_OPEN_MAX:
        raise Refused(f"over {BOARD_OPEN_MAX} board notes named like {pid!r}; not scanning them all")
    cands.sort(key=lambda c: (c[0] != pid, c[1]))  # this pattern's notes first
    for p, name in cands[:INDEX_OPEN_MAX]:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=board_fd)
            with os.fdopen(fd, "rb") as fh:
                if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                    continue
                head = fh.read(HEADER_SCAN)
        except OSError:
            continue
        front = head.split(b"\n---", 1)[0]
        for m in re.finditer(rb'(?m)^source: "nocap:([a-z0-9._-]{1,64}):' + re.escape(p.encode()) + rb'"\r?$', front):
            who = m.group(1).decode()
            if safe_agent(who) == who:
                idx["keys"].setdefault(f"{who}:{p}", name)
    try:
        ids_fd = os.open(".ids", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=board_fd)
    except OSError:
        ids_fd = -1
    if ids_fd >= 0:
        try:
            for name in _small_names(ids_fd, os.fstat(ids_fd)) or []:
                m = _IDS_NAME_RE.fullmatch(name)
                if m:
                    top = max(top, int(m.group(1)))
        finally:
            os.close(ids_fd)
    idx["next"] = top + 1
    return idx


# ---- the bridge ------------------------------------------------------------------------------------------------
class Bridge:
    def __init__(self, data_dir: Callable[[], Path], setting: Callable[[str, Any], Any], agent: Callable[[], str]):
        self.data_dir = data_dir
        self.setting = setting
        self.agent = agent
        self.last_error = ""
        self._pending: List[Tuple[Any, ...]] = []  # exports skipped on a busy folder (R1), retried by the next write
        self._plock = threading.Lock()

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
            return safe_agent(self.agent())  # unknown or empty identity: None, never a fallback to "default"
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

    def board_parts(self, vfd: int) -> Optional[List[str]]:
        """ABB's mistakes folder (from .agentbox.json, else ABB's default), or None when the board is off. Read
        relative to the held vault descriptor `vfd`."""
        mode = self.board_mode()
        if mode == "off":
            return None
        raw = _read_nofollow(Path(ABB_CONFIG), MAX_CONFIG_BYTES, dir_fd=vfd)
        try:
            has_data = stat.S_ISDIR(os.stat(ABB_DATA, dir_fd=vfd, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            has_data = False
        if mode == "auto" and raw is None and not has_data:
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
        return parts

    def board_dir(self, root: str, create: bool = True) -> Optional[Path]:
        with _vault_fd(root) as vfd:
            parts = self.board_parts(vfd)
        return _dir(root, parts, create) if parts is not None else None

    # -- writing --
    def record(self, receipts: List[Dict[str, Any]], session_id: str = "", turn_id: str = "",
               ts: Optional[float] = None, agent: Optional[str] = None) -> Dict[str, Any]:
        """Append one line per 🧢 in `receipts` to the agent's note, and the first board note per pattern.

        A destination folder locked by another writer is never waited for (R1): the export is skipped, kept in a
        small in-memory queue and written by the next write that gets the lock (at most PENDING_FLUSH per call);
        `hermes nocap obsidian sync` writes it from the store in any case (each line is idempotent by receipt id)."""
        out: Dict[str, Any] = {"written": 0, "board": [], "skipped": ""}
        caps = [r for r in receipts or [] if isinstance(r, dict) and r.get("verdict") == CAP]
        if not caps or not self.enabled():
            out["skipped"] = "off" if not self.enabled() else ""
            return out
        who = safe_agent(agent) if agent is not None else self.who()
        if not who:
            out["skipped"] = "agent name refused"
            self.last_error = "agent unknown or name refused (letters, digits, . _ - only); nothing attributed"
            return out
        item = (caps, str(session_id or ""), str(turn_id or ""), ts if ts is not None else time.time(), who)
        deadline = time.monotonic() + LOCK_BUDGET  # every lock this call takes shares one short budget
        out = self._record_one(*item, deadline=deadline)
        if out.pop("busy", False):
            self._queue(item)
            return out
        for _ in range(PENDING_FLUSH):  # the lock was free just now: earlier skipped exports, a few per write
            with self._plock:
                if not self._pending:
                    break
                prev = self._pending.pop(0)
            got = self._record_one(*prev, deadline=deadline)
            if got.pop("busy", False):
                self._queue(prev, front=True)
                break
            out["written"] += got["written"]
            out["board"] += got["board"]
        return out

    def pending(self) -> int:
        with self._plock:
            return len(self._pending)

    def _queue(self, item: Tuple[Any, ...], front: bool = False) -> None:
        with self._plock:
            if any(p[1:3] == item[1:3] and p[4] == item[4] and p[0] == item[0] for p in self._pending):
                return
            if front:
                self._pending.insert(0, item)
            else:
                self._pending.append(item)
            del self._pending[:-PENDING_MAX]  # oldest out first; `sync` still finds them in the store

    def _record_one(self, caps: List[Dict[str, Any]], session_id: str, turn_id: str, ts: float,
                    who: str, deadline: Optional[float] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {"written": 0, "board": [], "skipped": ""}
        try:
            root = self.vault()
            parts = safe_folder(self.folder())
            if parts is None:
                raise Refused("obsidian_folder must be a plain vault-relative folder")
            with _vault_fd(root) as vfd:
                where = (root, _ident(vfd))
                note_ids = [where[1]]
                with _pinned_dir(vfd, parts, idents=note_ids) as note_fd, _flock(note_fd, deadline):  # one lock/folder
                    path = Path(f"{who}.md")
                    old = _read_nofollow(path, MAX_NOTE_BYTES, dir_fd=note_fd)
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
                        if len(buf) > MAX_NOTE_BYTES:
                            raise Refused("agent note would exceed the size limit")
                        mode = ((os.stat(path, dir_fd=note_fd, follow_symlinks=False).st_mode & 0o777)
                                if old is not None else 0o600)
                        _replace(path, buf, mode, dir_fd=note_fd, check=lambda: _verify(root, parts, note_ids))
                link = "/".join(parts) + f"/{who}"
                for pid, r in firsts.items():
                    try:
                        made = self._board(vfd, who, pid, date, r, link, deadline, where)
                    except Busy as exc:  # skipped, not waited for: the whole item is retried later (idempotent)
                        out["busy"] = True
                        self.last_error = f"board: {exc}"
                        break
                    except (Refused, OSError) as exc:
                        self.last_error = f"board: {exc}"
                        continue
                    if made:
                        out["board"].append(made)
        except (Refused, OSError) as exc:
            out["written"] = 0
            out["skipped"] = str(exc)
            out["busy"] = isinstance(exc, Busy)
            self.last_error = str(exc)
        return out

    def _board(self, vfd: int, who: str, pid: str, date: str, r: Dict[str, Any], link: str,
               deadline: Optional[float] = None, where: Optional[Tuple[str, Tuple[int, int]]] = None) -> Optional[str]:
        parts = self.board_parts(vfd)
        if parts is None:
            return None
        root, vault_id = where if where is not None else ("", _ident(vfd))
        ids = [vault_id]
        with _pinned_dir(vfd, parts, idents=ids) as board_fd, _flock(board_fd, deadline):
            def check(sub: Optional[List[str]] = None, sub_ids: Optional[List[Tuple[int, int]]] = None) -> None:
                if root:
                    _verify(root, parts + (sub or []), ids + (sub_ids or []))
            return self._board_at(board_fd, who, pid, date, r, link, check)

    def _board_at(self, board_fd: int, who: str, pid: str, date: str,
                  r: Dict[str, Any], link: str, check: Callable[..., None] = lambda *a: None) -> Optional[str]:
        """Bounded per write, whatever the board's size (review 2, R4). No Cap keeps its own index of the board notes
        IT wrote (agent:pattern -> file name) and the next id hint, in the plugin data dir. A known note is one stat.
        A new id is the hint, taken with an exclusive create in .ids (the collision guard, as ABB does it), probed
        forward by galloping stat probes when taken. Only the first write to a board without an index lists the
        folder, and only a small one (folder size <= SCAN_DIR_BYTES, at most SCAN_MAX names): a big board is never
        listed, its id comes from the probes."""
        st = os.fstat(board_fd)
        idx_path = Path(self.data_dir()) / f"obsidian-board-{st.st_dev}-{st.st_ino}.json"
        idx = _load_index(idx_path)
        if idx is None:
            idx = _seed_index(board_fd, st, pid)
        key = f"{who}:{pid}"
        known = idx["keys"].get(key)
        if known:
            try:
                kst = os.stat(known, dir_fd=board_fd, follow_symlinks=False)
                if stat.S_ISREG(kst.st_mode):
                    _save_index(idx_path, idx)
                    return None  # an existing source key suppresses duplicates, but is never trusted as a rule
            except OSError:
                pass
            del idx["keys"][key]  # deleted or renamed by the user: a fresh note, as before
        # Open .ids relative to the already pinned board directory, even if an attacker renames its parent.
        check()
        try:
            os.mkdir(".ids", 0o700, dir_fd=board_fd)
        except FileExistsError:
            pass
        ids_fd = os.open(".ids", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=board_fd)
        ids_id = [_ident(ids_fd)]
        try:
            n = _free_id(ids_fd, max(1, idx["next"]))
            for _ in range(ID_TRIES):
                try:
                    _write_new(Path(f"{n:04d}"), b"", dir_fd=ids_fd, check=lambda: check([".ids"], ids_id))
                except FileExistsError:
                    n = _free_id(ids_fd, n + 1)
                    continue
                name, text = board_note(n, who, pid, date, _claim(r), _evidence(r), link)
                try:
                    _write_new(Path(name), text.encode("utf-8"), dir_fd=board_fd, check=check)
                except FileExistsError:
                    n += 1
                    continue
                idx["next"] = n + 1
                idx["keys"][key] = name
                _save_index(idx_path, idx)
                return name
            raise Refused(f"could not reserve a board id after {ID_TRIES} tries")
        finally:
            os.close(ids_fd)

    def sync(self, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Backfill from the local store: every stored 🧢, idempotent per receipt id."""
        total: Dict[str, Any] = {"written": 0, "board": [], "skipped": ""}
        for rec in records:
            if not isinstance(rec, dict) or rec.get("type", "reply") != "reply" or not rec.get("receipts"):
                continue
            if not any(isinstance(x, dict) and x.get("verdict") == CAP for x in rec["receipts"]):
                continue
            agent = safe_agent(rec.get("profile"))
            if not agent:
                total["skipped"] = "record has no valid profile; not attributed to the current agent"
                continue
            got = self.record(rec["receipts"], str(rec.get("session_id") or ""), str(rec.get("turn_id") or ""),
                              ts=rec.get("ts"), agent=agent or "")
            total["written"] += got["written"]
            total["board"] += got["board"]
            if got["skipped"] and got["skipped"] != "off":
                total["skipped"] = got["skipped"]
        return total

    # -- learning --
    def lessons_cached(self, store: Path, exclude: Iterable[str] = ()) -> Optional[str]:
        """pre_llm_call's lesson line, from the lessons cache (R3): bounded work per turn, whatever the store size."""
        if not self.learn_on():
            return None
        who = self.who()
        if not who:
            return None
        counts = lesson_counts(Path(store), Path(self.data_dir()) / LESSONS_FILE)
        return lesson_from_counts(counts.get(who, {}), who, exclude)

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
        if self.pending():
            lines.append(f"waiting: {self.pending()} 🧢 export(s) skipped on a busy folder; the next write or "
                         "`hermes nocap obsidian sync` writes them")
        return "\n".join(lines)

    def doctor_line(self) -> Tuple[str, bool]:
        if not self.enabled():
            return "ℹ️ Obsidian lessons: off (obsidian_vault not set).", False
        if fcntl is None:
            return "❌ Obsidian lessons: writes require POSIX directory handles and flock.", True
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
