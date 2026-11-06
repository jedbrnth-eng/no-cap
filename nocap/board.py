"""Cap Board: who caps most, per agent (Hermes profile), model and skill. Read-only, local, no model.

Scope (security): by default the board shows ONLY the profile it is asked from. The multi-profile team view is an
explicit opt-in (``plugins.entries.no-cap.settings.board.team_profiles``: a list of names or ``all``) and is only
served on ``cli`` and the dashboard; a gateway chat always gets the current profile (``scoped_sources``).

Each profile (HERMES_HOME) keeps its own receipt store under ``plugin-data/``. The board finds them the way Hermes
finds profiles (the root home is ``default``, ``<root>/profiles/<name>`` the named ones; ghosts without an identity
file and tombstoned profiles are skipped), reads them without ever writing, and aggregates per agent (profile), per
model and per skill (skills loaded in the turn with ``skill_view``).

Numbers, per row:
  replies   checked replies (store records of type ``reply``)
  claims    receipts on those replies (every claim No Cap judged, stamped or not)
  cap_rate  🧢 / claims; receipt_rate 🧾 / claims. Both are None below ``min_claims`` (default 10): a rate on three
            claims is noise, and ranking an agent publicly on it would be unfair. The counts are still shown, with n.
  streak    all-🧾 replies since the last reply that had a 🧢 (a 🤔 reply neither extends nor resets it)
  trend     cap rate over the last 7 days vs the 7 before (same min-sample rule in each window)
  top_cap   the claim kind capped most often (tests, pushed, merged, ...)
The Hall of Cap lists the latest 🧢 with the claim and the evidence that contradicted it, redacted again at read time.
"""
from __future__ import annotations

import gc
import glob
import hashlib
import heapq
import json
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import score
from .evidence import redact

MIN_CLAIMS = 10
WEEK = 7 * 86400.0
HALL_SIZE = 12
NO_SKILL = "(no skill)"
FLAT = 0.02  # a trend under 2 points either way is flat
STORE_FILE = "receipts.jsonl"
PLUGIN_ID = "no-cap"
# Hermes names a plugin's data dir agent-plugin-<slug>-<sha256(id)[:8]> (hermes_cli/plugins_manifest.py:59-63,
# via PluginState.data_dir); older builds used plugin-data/<id>. Both are read.
NAMESPACES = (f"agent-plugin-{PLUGIN_ID}-" + hashlib.sha256(PLUGIN_ID.encode()).hexdigest()[:8], PLUGIN_ID)
_NS_RE = re.compile(r"^agent-plugin-no-cap-[0-9a-f]{8}$")
# Mirrors hermes_constants.PROFILE_ID_RE and _PROFILE_IDENTITY_MARKERS for hosts where it can't be imported.
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MARKERS = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")
MAX_GLOB_FILES = 5000
MAX_WALK_DEPTH = 6  # a board_sources folder is searched this many levels down at most
MAX_WALK_DIRS = 2000  # and opens at most this many directories, whatever the tree holds
TEAM_PLATFORMS = ("cli", "dashboard")  # the only surfaces that may show other profiles (team mode)


def _hc():
    try:
        import hermes_constants  # documented public module
        return hermes_constants
    except Exception:
        return None


# ---- identity: which profile is this turn running as ---------------------------------------------------------
def profile_name() -> str:
    """The profile the current turn runs FOR, as Hermes names it (hermes_cli/profiles.py:1997
    ``current_profile_name``): a launcher pin (HERMES_PROFILE_NAME / HERMES_PROFILE) unless a per-turn home override
    is bound, else the profile owning HERMES_HOME (``default`` for a root home)."""
    hc = _hc()
    override = None
    if hc is not None:
        try:
            override = hc.get_hermes_home_override()
        except Exception:
            override = None
    if override is None:
        for env in ("HERMES_PROFILE_NAME", "HERMES_PROFILE"):
            v = (os.environ.get(env) or "").strip()
            if v:
                return v[:64]
    if hc is not None:
        try:
            name = hc.profile_name_for_home(hc.get_hermes_home())
            if name:
                return str(name)
        except Exception:
            pass
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    if home.parent.name == "profiles" and _PROFILE_RE.match(home.name):
        return home.name
    return "default"


def hermes_root() -> Path:
    hc = _hc()
    if hc is not None:
        try:
            return Path(hc.get_default_hermes_root())
        except Exception:
            pass
    env = (os.environ.get("HERMES_HOME") or "").strip()
    if env:
        home = Path(env).expanduser()
        return home.parent.parent if home.parent.name == "profiles" else home
    return Path.home() / ".hermes"


# ---- discovery --------------------------------------------------------------------------------------------------
@dataclass
class Source:
    label: str
    paths: List[Path] = field(default_factory=list)
    explicit: bool = False  # a user-labelled source: its label names the agent, whatever the records say


def home_stores(home: Path) -> List[Path]:
    pd = Path(home) / "plugin-data"
    found: List[Path] = []
    try:
        names = sorted(d.name for d in pd.iterdir() if d.is_dir())
    except OSError:
        return found
    ordered = [n for n in NAMESPACES if n in names] + [n for n in names if _NS_RE.match(n) and n not in NAMESPACES]
    for n in ordered:
        f = pd / n / STORE_FILE
        if f.is_file():
            found.append(f)
    return found


def _is_profile(d: Path) -> bool:
    hc = _hc()
    if hc is not None:
        try:
            return bool(hc.PROFILE_ID_RE.match(d.name) and hc.named_profile_has_identity(d)
                        and not hc.named_profile_is_deleted(d))
        except Exception:
            pass
    if not _PROFILE_RE.match(d.name):
        return False
    if not any((d / m).is_file() or (d / m).is_symlink() for m in _MARKERS):
        return False
    return not (d.parent / ".deleted" / d.name).exists()


def profile_homes(root: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """``[("default", root), (name, root/profiles/name), ...]`` like hermes_cli/profiles.py:481-511
    (``_iter_named_profile_dirs`` / ``list_profile_names``), from public hermes_constants helpers only."""
    root = Path(root) if root is not None else hermes_root()
    out = [("default", root)]
    try:
        dirs = sorted((root / "profiles").iterdir())
    except OSError:
        return out
    out.extend((d.name, d) for d in dirs if d.is_dir() and d.name != "default" and _is_profile(d))
    return out


def parse_sources(spec: Any) -> List[Tuple[Optional[str], str]]:
    """Extra stores: ``label=path`` or ``path`` entries, separated by os.pathsep or newlines (or a list). A path may be
    a Hermes home, a receipts.jsonl, a folder to search for receipts.jsonl, or a glob of any of those."""
    items: Iterable[Any]
    if isinstance(spec, (list, tuple)):
        items = spec
    else:
        items = re.split(r"[\n" + re.escape(os.pathsep) + r"]", str(spec or ""))
    out: List[Tuple[Optional[str], str]] = []
    for item in items:
        item = str(item or "").strip()
        if not item:
            continue
        label, sep, path = item.partition("=")
        if sep and label and "/" not in label and "\\" not in label:
            out.append((label.strip()[:64], path.strip()))
        else:
            out.append((None, item))
    return out


def _walk(top: Path) -> List[Path]:
    """Stores under ``top``, breadth first, bounded BEFORE the walk: at most ``MAX_WALK_DEPTH`` levels, ``MAX_WALK_DIRS``
    directories opened and ``MAX_GLOB_FILES`` stores. Symlinked directories are never entered (no loops, no escape)."""
    found: List[Path] = []
    queue: List[Tuple[Path, int]] = [(top, 0)]
    opened = 0
    while queue and opened < MAX_WALK_DIRS and len(found) < MAX_GLOB_FILES:
        d, depth = queue.pop(0)
        opened += 1
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if depth + 1 <= MAX_WALK_DEPTH:
                        queue.append((Path(e.path), depth + 1))
                elif e.name == STORE_FILE and e.is_file(follow_symlinks=False):
                    found.append(Path(e.path))
                    if len(found) >= MAX_GLOB_FILES:
                        break
            except OSError:
                continue
    return found


def _paths_of(pattern: str) -> List[Path]:
    pattern = os.path.expanduser(pattern)
    matches = sorted(glob.glob(pattern)) if any(c in pattern for c in "*?[") else [pattern]
    files: List[Path] = []
    for m in matches:
        p = Path(m)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            if (p / "plugin-data").is_dir():
                files.extend(home_stores(p))
            elif (p / STORE_FILE).is_file():
                files.append(p / STORE_FILE)
            else:
                files.extend(_walk(p))
    seen, uniq = set(), []
    for f in files:
        k = str(f)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def _label_for(pattern: str) -> str:
    p = Path(os.path.expanduser(pattern.split("*")[0].rstrip("/")) or ".")
    if p.parent.name == "profiles" and _PROFILE_RE.match(p.name):
        return p.name
    return (p.name or str(p))[:64]


def env_sources() -> List[Tuple[Optional[str], str]]:
    return parse_sources(os.environ.get("NOCAP_BOARD_SOURCES", ""))


def discover_sources(root: Optional[Path] = None, extra: Optional[Sequence[Tuple[Optional[str], str]]] = None) \
        -> List[Source]:
    """Every profile under the Hermes root, plus labelled extra stores. Sources without a store are dropped."""
    out: List[Source] = []
    seen = set()
    for name, home in profile_homes(root):
        paths = [p for p in home_stores(home) if str(p.resolve()) not in seen]
        seen.update(str(p.resolve()) for p in paths)
        if paths:
            out.append(Source(name, paths))
    for label, pattern in (env_sources() if extra is None else extra):
        paths = [p for p in _paths_of(pattern) if str(p.resolve()) not in seen]
        seen.update(str(p.resolve()) for p in paths)
        if not paths:
            continue
        lab = label or _label_for(pattern)
        same = next((s for s in out if s.label == lab), None)
        if same is not None:
            same.paths.extend(paths)
            same.explicit = same.explicit or bool(label)
        else:
            out.append(Source(lab, paths, explicit=bool(label)))
    return out


def parse_team(spec: Any) -> Any:
    """``board.team_profiles``: ``None`` (team view off, the default), ``"all"``, or a list of profile names.
    Anything else (a number, a bad name) is off or dropped: the multi-profile view needs a clear opt-in."""
    if spec is None or isinstance(spec, bool):
        return None
    if isinstance(spec, str):
        items = [x for x in re.split(r"[\s,]+", spec.strip()) if x]
    elif isinstance(spec, (list, tuple)):
        items = [str(x).strip() for x in spec if isinstance(x, str) and str(x).strip()]
    else:
        return None
    low = [x.lower() for x in items]
    if any(x in ("all", "*") for x in low):
        return "all"
    if not items or low in (["off"], ["none"], ["false"], ["no"]):
        return None
    names = [x for x in items if _PROFILE_RE.match(x)]
    return names or None


def current_home() -> Path:
    """The home of the profile the request/turn is scoped to (Hermes binds it per request)."""
    hc = _hc()
    if hc is not None:
        try:
            return Path(hc.get_hermes_home())
        except Exception:
            pass
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def scoped_sources(team: Any = None, platform: str = "", root: Optional[Path] = None,
                   extra: Optional[Sequence[Tuple[Optional[str], str]]] = None) -> Tuple[List[Source], Dict[str, Any]]:
    """What the board may show, and why.

    Default: ONLY the current profile's own store (extra ``board_sources`` are ignored too). The team view (other
    profiles, extra stores) needs ``board.team_profiles`` set AND a local surface (``cli`` or the dashboard); a
    gateway chat (telegram, discord, ...), the TUI, Desktop or an unknown platform always gets the current profile."""
    me = profile_name()
    want = parse_team(team)
    surface = str(platform or "").strip().lower()
    if want is None or surface not in TEAM_PLATFORMS:
        paths = home_stores(current_home())
        srcs = [Source(me, paths)] if paths else []
        return srcs, {"mode": "profile", "profile": me, "team_setting": want is not None, "profiles": [me]}
    srcs = discover_sources(root=root, extra=extra if extra is not None else [])
    if want != "all":
        allowed = set(want) | {me}
        names = {n for n, _ in profile_homes(root)}
        srcs = [s for s in srcs if (s.label in allowed) or (s.label not in names)]
        profiles = [n for n, _ in profile_homes(root) if n in allowed]
    else:
        profiles = [n for n, _ in profile_homes(root)]
    return srcs, {"mode": "team", "profile": me, "team_setting": True, "profiles": profiles}


# ---- read-only, incremental store reader ---------------------------------------------------------------------
@dataclass
class _Cached:
    ino: int
    size: int
    mtime: int
    offset: int
    total: int = 0  # valid records (dict lines), any type
    bad: int = 0
    recs: List[Dict[str, Any]] = field(default_factory=list)


_CACHE: Dict[str, _Cached] = {}
_LOCK = threading.Lock()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _slim(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the board keeps of a reply record: identity, time and the verdicts. Ledger calls are dropped."""
    if (rec.get("type") or "reply") != "reply":
        return None
    try:
        ts = float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    raw = rec.get("receipts")
    receipts = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    skills = rec.get("skills")
    skills = sorted({str(s)[:80] for s in skills if isinstance(s, str) and s}) if isinstance(skills, list) else []
    caps, proven, unsure = [], 0, 0
    for r in receipts:
        v = r.get("verdict")
        if v == "CAP":
            caps.append(r)
        elif v == "NO_CAP":
            proven += 1
        elif v == "NO_RECEIPT":
            unsure += 1
    profile = rec.get("profile")
    return {
        "ts": ts, "model": str(rec.get("model") or "unknown")[:120],
        "profile": profile if isinstance(profile, str) else "",
        "skills": skills, "n": len(receipts), "cap": len(caps), "proven": proven, "unsure": unsure,
        "clean": score.all_proven({"receipts": receipts}),  # every shown receipt is 🧾: counts toward the streak
        "cap_kinds": [str(r.get("kind") or "claim") for r in caps], "caps": caps,
    }


_loads = json.JSONDecoder().decode
# The ledger's cited calls are most of a record's bytes and the board reads none of them. In the store's own key
# order they sit between '"calls": [' and '], "ledger": '; inside a JSON string every quote is escaped, so the cut
# can't land in one. A line the cut doesn't fit is parsed whole.
_CALLS, _LEDGER = b'"calls": [', b'], "ledger": '
_BLOCK = 512  # lines parsed per json call; a bad line only sends its own block down the slow path


def _cut(line: bytes) -> bytes:
    i = line.find(_CALLS)
    if i > 0:
        j = line.find(_LEDGER, i)
        if j > 0 and line.find(b'"receipts": ', i, j) < 0:  # another writer's key order: never cut the verdicts
            return line[:i] + line[j + 3:]
    return line


def _load_line(line: bytes) -> Any:
    try:
        return _loads(_cut(line).decode("utf-8"))
    except ValueError:
        return _loads(line.decode("utf-8"))


def _take(rec: Any, entry: _Cached) -> None:
    if not isinstance(rec, dict):
        entry.bad += 1
        return
    entry.total += 1
    slim = _slim(rec)
    if slim is not None:
        entry.recs.append(slim)


def _parse(chunk: bytes, entry: _Cached) -> None:
    lines = [ln for ln in chunk.split(b"\n") if ln and not ln.isspace()]
    for i in range(0, len(lines), _BLOCK):
        block = lines[i:i + _BLOCK]
        try:  # fast path: one json call for the whole block
            recs = _loads((b"[" + b",".join([_cut(ln) for ln in block]) + b"]").decode("utf-8"))
            if len(recs) != len(block):
                raise ValueError("line count")
        except ValueError:  # includes UnicodeDecodeError: one line at a time, bad lines counted
            recs = []
            for line in block:
                try:
                    recs.append(_load_line(line))
                except ValueError:
                    recs.append(None)
        for rec in recs:
            _take(rec, entry)


def read_store(path: Path) -> _Cached:
    """Records of one store. Opened read-only; only complete lines are consumed (a writer mid-append is picked up
    on the next read); appends are read incrementally; a pruned, purged or replaced file is read again in full."""
    key = str(path)
    try:
        fh = open(path, "rb")
    except OSError:
        with _LOCK:
            _CACHE.pop(key, None)
        return _Cached(0, 0, 0, 0)
    with fh, _LOCK:
        st = os.fstat(fh.fileno())
        entry = _CACHE.get(key)
        if entry and entry.ino == st.st_ino and entry.size == st.st_size and entry.mtime == st.st_mtime_ns:
            return entry
        if not entry or entry.ino != st.st_ino or st.st_size < entry.offset:
            entry = _Cached(st.st_ino, 0, 0, 0)
        fh.seek(entry.offset)
        data = fh.read(max(0, st.st_size - entry.offset))
        cut = data.rfind(b"\n") + 1
        # Parsing allocates thousands of small dicts and none are cycles; the cyclic GC walking the heap (and the
        # host's heap with it) on every allocation burst would cost more than the parse. Paused only for the parse.
        was_on = gc.isenabled()
        gc.disable()
        try:
            _parse(data[:cut], entry)
        finally:
            if was_on:
                gc.enable()
        entry.offset += cut
        entry.size, entry.mtime = st.st_size, st.st_mtime_ns
        _CACHE[key] = entry
        return entry


# ---- aggregation --------------------------------------------------------------------------------------------------
def _agent(src: Source, rec: Dict[str, Any]) -> str:
    if src.explicit:
        return src.label
    p = rec.get("profile") or ""
    return p[:64] if p and p != "custom" else src.label


def _rate(num: int, den: int, min_claims: int) -> Optional[float]:
    return (num / den) if den and den >= min_claims else None


def _row(name: str, recs: List[Dict[str, Any]], now: float, min_claims: int) -> Dict[str, Any]:
    """One leaderboard row; *recs* arrive in store order, so they are sorted by time here (streak, last_ts)."""
    recs = sorted(recs, key=lambda r: r["ts"]) if any(
        recs[k]["ts"] > recs[k + 1]["ts"] for k in range(len(recs) - 1)) else recs
    claims = cap = proven = unsure = capped = n_cur = c_cur = n_prev = c_prev = 0
    lo_cur, lo_prev = now - WEEK, now - 2 * WEEK
    kinds: Counter = Counter()
    models: Counter = Counter()
    for r in recs:
        n, c = r["n"], r["cap"]
        claims += n
        cap += c
        proven += r["proven"]
        unsure += r["unsure"]
        models[r["model"]] += 1
        if c:
            capped += 1
            kinds.update(r["cap_kinds"])
        ts = r["ts"]
        if ts > lo_cur:
            n_cur += n
            c_cur += c
        elif ts > lo_prev:
            n_prev += n
            c_prev += c
    streak = 0
    for r in reversed(recs):
        if r["cap"]:
            break
        if r["clean"]:
            streak += 1  # only all-🧾 replies count; a 🤔 reply neither extends nor resets
    cur, prev = _rate(c_cur, n_cur, min_claims), _rate(c_prev, n_prev, min_claims)
    trend: Dict[str, Any] = {"cur": cur, "prev": prev, "n_cur": n_cur, "n_prev": n_prev, "delta": None, "dir": None}
    if cur is not None and prev is not None:
        d = cur - prev
        trend.update(delta=d, dir="up" if d >= FLAT else "down" if d <= -FLAT else "flat")
    return {
        "name": name, "replies": len(recs), "claims": claims, "cap": cap, "proven": proven, "unsure": unsure,
        "capped_replies": capped,
        "cap_rate": _rate(cap, claims, min_claims), "receipt_rate": _rate(proven, claims, min_claims),
        "low_sample": claims < min_claims, "streak": streak, "trend": trend,
        "top_cap": kinds.most_common(1)[0][0] if kinds else None,
        "model": models.most_common(1)[0][0] if models else None, "models": len(models),
        "last_ts": recs[-1]["ts"] if recs else None, "rank": None,
    }


def _rank(groups: Dict[str, List[Dict[str, Any]]], now: float, min_claims: int) -> List[Dict[str, Any]]:
    rows = [_row(k, v, now, min_claims) for k, v in groups.items()]
    ranked = sorted((r for r in rows if r["cap_rate"] is not None), key=lambda r: (-r["cap_rate"], -r["cap"], r["name"]))
    rest = sorted((r for r in rows if r["cap_rate"] is None), key=lambda r: (-r["claims"], r["name"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked + rest


def _skills_of(rec: Dict[str, Any]) -> List[str]:
    return rec["skills"] or [NO_SKILL]


def _hall_item(agent: str, rec: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    claim = (r.get("claim") or {}).get("frag") if isinstance(r.get("claim"), dict) else None
    claim = claim or r.get("text") or ""
    evidence = r.get("quote") or r.get("why") or ""
    return {
        "ts": rec["ts"], "agent": agent, "model": rec["model"], "skills": rec["skills"],
        "kind": str(r.get("kind") or "claim")[:40],
        "claim": redact(str(claim))[:160], "evidence": redact(str(evidence))[:220],
        "cmd": redact(str(r.get("cmd") or ""))[:120], "cite": r.get("cite") if isinstance(r.get("cite"), int) else None,
    }


def _pairs(sources: Sequence[Source]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    for src in sources:
        for p in src.paths:
            for rec in read_store(p).recs:
                yield _agent(src, rec), rec


def signature(sources: Sequence[Source]) -> str:
    """Changes whenever any store changes (size, mtime, inode): lets a polling client skip unchanged boards."""
    h = hashlib.sha256()
    for src in sources:
        for p in src.paths:
            try:
                st = os.stat(p)
                h.update(f"{src.label}|{p}|{st.st_ino}|{st.st_size}|{st.st_mtime_ns}\n".encode())
            except OSError:
                h.update(f"{src.label}|{p}|-\n".encode())
    return h.hexdigest()[:16]


def build_board(sources: Sequence[Source], agent: str = "", model: str = "", skill: str = "",
                min_claims: int = MIN_CLAIMS, now: Optional[float] = None, hall_size: int = HALL_SIZE) -> Dict[str, Any]:
    now = time.time() if now is None else now
    min_claims = max(1, int(min_claims or MIN_CLAIMS))
    pairs = list(_pairs(sources))
    opts_agents, opts_models, opts_skills = set(), set(), set()
    by_agent: Dict[str, List[Dict[str, Any]]] = {}
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    by_skill: Dict[str, List[Dict[str, Any]]] = {}
    hall: List[Tuple[float, str, Dict[str, Any], Dict[str, Any]]] = []
    t_rep = t_claims = t_cap = t_proven = t_unsure = 0
    for who, rec in pairs:
        sk = _skills_of(rec)
        opts_agents.add(who)
        opts_models.add(rec["model"])
        opts_skills.update(sk)
        if (agent and who != agent) or (model and rec["model"] != model) or (skill and skill not in sk):
            continue
        by_agent.setdefault(who, []).append(rec)
        by_model.setdefault(rec["model"], []).append(rec)
        for s in sk:
            by_skill.setdefault(s, []).append(rec)
        t_rep += 1
        t_claims += rec["n"]
        t_cap += rec["cap"]
        t_proven += rec["proven"]
        t_unsure += rec["unsure"]
        for r in rec["caps"]:
            hall.append((rec["ts"], who, rec, r))
    hall = heapq.nlargest(max(0, hall_size), hall, key=lambda x: x[0])
    totals = dict(replies=t_rep, claims=t_claims, cap=t_cap, proven=t_proven, unsure=t_unsure, agents=len(by_agent),
                  cap_rate=_rate(t_cap, t_claims, min_claims), receipt_rate=_rate(t_proven, t_claims, min_claims))
    sources_out = []
    for src in sources:
        entries = [read_store(p) for p in src.paths]
        sources_out.append({"label": src.label, "stores": len(src.paths), "records": sum(e.total for e in entries),
                            "bad_lines": sum(e.bad for e in entries)})
    skills_sorted = sorted(s for s in opts_skills if s != NO_SKILL) + ([NO_SKILL] if NO_SKILL in opts_skills else [])
    return {
        "generated_at": now, "min_claims": min_claims, "window_days": 7,
        "filters": {"agent": agent, "model": model, "skill": skill},
        "totals": totals,
        "agents": _rank(by_agent, now, min_claims), "models": _rank(by_model, now, min_claims),
        "skills": _rank(by_skill, now, min_claims),
        "hall": [_hall_item(who, rec, r) for _, who, rec, r in hall],
        "options": {"agents": sorted(opts_agents), "models": sorted(opts_models), "skills": skills_sorted},
        "sources": sources_out, "version": signature(sources),
    }


# ---- text ----------------------------------------------------------------------------------------------------
def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.0%}"


def trend_text(t: Dict[str, Any]) -> str:
    if not t or t.get("dir") is None:
        return "trend: not enough data"
    pts = round((t["delta"] or 0) * 100)
    return {"up": f"↑ +{pts} pts", "down": f"↓ {pts} pts", "flat": "→ flat"}[t["dir"]] + " vs prior 7d"


def row_text(r: Dict[str, Any], min_claims: int, with_model: bool = False) -> str:
    who = r["name"] + (f" ({r['model']})" if with_model and r.get("model") else "")
    if r["cap_rate"] is None:
        return (f"–  {who} · n={r['claims']} claims, too few to rate (min {min_claims}) · "
                f"🧢 {r['cap']} · 🧾 {r['proven']}")
    bits = [f"{r['rank']}. {who}", f"🧢 {_pct(r['cap_rate'])} cap rate ({r['cap']}/{r['claims']} claims)",
            f"🧾 {_pct(r['receipt_rate'])} receipts", f"🔥 {r['streak']}", trend_text(r["trend"])]
    if r.get("top_cap"):
        bits.append(f"top cap: {r['top_cap']}")
    return " · ".join(bits)


def scope_text(scope: Optional[Dict[str, Any]]) -> str:
    if not scope:
        return ""
    if scope.get("mode") == "team":
        return f"team view: {', '.join(scope.get('profiles') or [])} (board.team_profiles)"
    note = f"this profile only ({scope.get('profile') or 'default'})"
    if scope.get("team_setting"):
        note += " · the team view is only shown in the CLI and the dashboard"
    return note


def board_text(b: Dict[str, Any], limit: int = 8, hall: int = 5) -> str:
    t = b["totals"]
    where = scope_text(b.get("scope"))
    if not t["replies"]:
        return ("🧢 Cap Board: no checked replies yet" + (f" ({where})" if where else "")
                + ". Make a claim, get a receipt.")
    n = b["min_claims"]
    lines = [f"🧢 **Cap Board** · top cappers across {t['agents']} agent(s) · {t['replies']} replies, "
             f"{t['claims']} claims · rates need ≥{n} claims" + (f" · {where}" if where else "")]
    for title, key, with_model in (("Agents", "agents", True), ("Models", "models", False), ("Skills", "skills", False)):
        rows = b[key]
        if not rows:
            continue
        lines.append(f"**{title}**")
        lines.extend("  " + row_text(r, n, with_model) for r in rows[:limit])
        if len(rows) > limit:
            lines.append(f"  … {len(rows) - limit} more")
    if b["hall"]:
        lines.append("**Hall of Cap** (latest 🧢)")
        for h in b["hall"][:hall]:
            when = time.strftime("%m-%d %H:%M", time.localtime(h["ts"])) if h["ts"] else "?"
            skills = f" [{', '.join(h['skills'])}]" if h["skills"] else ""
            lines.append(f"  🧢 {when} {h['agent']} · {h['model']}{skills} · “{h['claim'][:80]}” → "
                         f"{h['evidence'][:100] or 'contradicted'}")
    bad = sum(s["bad_lines"] for s in b["sources"])
    if bad:
        lines.append(f"({bad} unreadable store line(s) skipped)")
    lines.append("Dashboard: the Cap Board tab · /capscore → this profile's per-model score")
    return "\n".join(lines)
