"""Cap Coach: learn what an agent caps on, propose a fix, let the user approve it, and measure whether it helped.

Three deterministic parts, no extra model and no network:
  mine()      → cluster the 🧢 CAP and 🤔 NO RECEIPT receipts in the local store by failure shape, model and skill
  propose()   → map each pattern with enough evidence to a template fix: a coach rule (the default path), plus a
                skill-patch diff and a memory note the user can choose instead
  measure()   → cap rate on that pattern before approval (a window) and after, with n, a Wilson 95% interval and
                a two-proportion z-test; "not enough data yet" below the minimum sample

Nothing here edits a user's skills, memory or config. A proposal is a draft until `/cap coach approve <id>`.
An approved coach rule lives in this plugin's own data dir (coach.json) and reaches the model only through the
public pre_llm_call hook, as context that names itself; `/cap coach revert <id>` turns it off. A skill patch or
memory note is shown as exact text; on approval No Cap can ask the agent (inject_message) to apply it with its own
skill_manage / memory tools, which the agent may decline, and `/cap coach status` checks the file to see.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import math
import os
import re
import threading
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .evidence import redact

MAX_SESSIONS = 256  # sessions whose loaded skills / injected rule ids are kept in memory

FILE = "coach.json"
MODES = ("off", "suggest", "auto")
DEFAULTS = {
    "mode": "suggest",       # off | suggest | auto-suggest-after-N-caps (alias: auto)
    "min_evidence": 5,       # caps of the same pattern before a fix is proposed
    "auto_after_caps": 0,    # auto mode: announce a fix once a pattern reaches this many caps (0 = min_evidence)
    "window_days": 14,       # baseline window before approval
    "min_sample": 10,        # replies in scope needed on each side before a before/after rate is shown
    "max_rules": 5,          # most coach rules injected into one turn
}
CAP, NO_RECEIPT, NO_CAP = "CAP", "NO_RECEIPT", "NO_CAP"
EXAMPLES = 3
ANY = "*"


# ---- settings ---------------------------------------------------------------------------------------------------
def settings(setting: Callable[[str, Any], Any]) -> Dict[str, Any]:
    """plugins.entries.no-cap.settings.coach.* with defaults; a bad value falls back to its default."""
    raw = {}
    try:
        raw = setting("coach", {}) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = dict(DEFAULTS)
    mode = str(raw.get("mode", DEFAULTS["mode"]) or "").strip().lower()
    if mode.startswith("auto"):
        out["mode"] = "auto"
        m = re.search(r"(\d+)", mode)  # "auto-suggest-after-8-caps"
        if m:
            out["auto_after_caps"] = int(m.group(1))
    elif mode in MODES:
        out["mode"] = mode
    for key in ("min_evidence", "auto_after_caps", "window_days", "min_sample", "max_rules"):
        if key in raw:
            try:
                v = int(raw[key])
                if v >= 0:
                    out[key] = v
            except (TypeError, ValueError):
                pass
    out["min_evidence"] = max(1, out["min_evidence"])
    out["min_sample"] = max(1, out["min_sample"])
    out["window_days"] = max(1, out["window_days"])
    if not out["auto_after_caps"]:
        out["auto_after_caps"] = out["min_evidence"]
    return out


# ---- the failure-shape library ----------------------------------------------------------------------------------
# Each pattern: id, the claim kind it belongs to, which receipts it matches (verdict and/or the receipt's `why`),
# a title in plain words, and the fix: a coach rule, the reason, and the skill-section / memory-note variants.
def _why(*phrases: str) -> Callable[[Dict[str, Any]], bool]:
    low = tuple(p.lower() for p in phrases)
    return lambda r: any(p in (r.get("why") or "").lower() for p in low)


def _verdict(v: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda r: r.get("verdict") == v


PATTERNS: List[Dict[str, Any]] = [
    {"id": "tests.failed_run", "kind": "tests", "match": _verdict(CAP),
     "title": "claims tests pass while the latest run failed",
     "rule": "Never say the tests pass when the latest test run in this turn failed. Quote the failing summary "
             "line, then fix and re-run, or say plainly which tests still fail.",
     "why": "the test output in the same turn said the opposite of the claim"},
    {"id": "tests.subset_only", "kind": "tests",
     "match": _why("only a subset of the tests ran", "the claim also covers the full suite"),
     "title": "claims all tests pass after running only a subset (-k, one file, one test)",
     "rule": "Before you say all tests pass, run the full suite with the project's test command (no -k, ::, or "
             "single-file filter) after your last edit, and quote its summary line. If you only ran a subset, say which.",
     "why": "a filtered run proves only the tests it selected, not the suite"},
    {"id": "tests.named_unshown", "kind": "tests", "match": _why("no run of that scope after the last code edit"),
     "title": "claims a named test passes, but no run after the last edit shows that test passing",
     "rule": "When you say a specific test passes, quote the line from a run after your last edit that shows it "
             "passing, or run the full suite and quote its summary line. Don't infer a pass from the code.",
     "why": "no run after the last edit names that test or shows the suite green"},
    {"id": "tests.stale_after_edit", "kind": "tests",
     "match": _why("code changed after", "after the last code edit"),
     "title": "claims tests pass, but edited code after the last test run",
     "rule": "If you edit code after a test run, run the tests again before you claim they pass. The result you "
             "report must come from a run after your last edit; quote that run's summary line.",
     "why": "a run from before the last edit says nothing about the code you are reporting on"},
    {"id": "tests.no_run", "kind": "tests",
     "match": _why("no test run in this turn", "no tests ran", "no run of that scope in this turn",
                   "not from a test run we can attribute", "only the agent's own check script ran"),
     "title": "claims tests pass without running the test suite in that turn",
     "rule": "Don't say the tests pass unless you ran the test suite in this turn. Run it and quote the summary "
             "line, or write 'tests not run'.",
     "why": "nothing in the turn ran the tests the claim is about"},
    {"id": "tests.hidden_result", "kind": "tests",
     "match": _why("cut by a pipe", "exit code hidden", "no reliable exit code"),
     "title": "claims a pass from test output piped through head, tail or grep (result hidden)",
     "rule": "Run the tests without piping them through head, tail or grep, so the summary line and exit code "
             "are visible, and quote the summary line.",
     "why": "a pipe hides the exit code and can cut the failing part of the output"},
    {"id": "tests.count_mismatch", "kind": "tests",
     "match": _why("no run shows", "another count", "no output shows that count"),
     "title": "quotes a test count that no run shows",
     "rule": "Only quote test counts you copied from the latest run's summary line; don't estimate them.",
     "why": "the counts in the reply didn't match any run in the turn"},
    {"id": "tests.mixed_results", "kind": "tests",
     "match": _why("mixed results", "also shows failures", "didn't pass", "also had failures",
                   "may mean another suite", "may mean another part"),
     "title": "says 'tests pass' when a run in the same turn shows failures",
     "rule": "When any test run in this turn failed, name which suite passed and which failed; don't sum it up "
             "as 'tests pass'.",
     "why": "the turn had failing runs next to the passing ones"},
    {"id": "tests.skip_after_fail", "kind": "tests", "match": _why("marked skip after a failing run", "suite was changed",
                                                                  "failing test was removed"),
     "title": "skips a failing test, then reports a green run",
     "rule": "Don't skip, xfail or delete a failing test to get a green run. If you had to, say so in the reply.",
     "why": "a skipped failure isn't a pass"},
    {"id": "pushed.wrong_ref", "kind": "pushed", "match": _verdict(CAP),
     "title": "claims a push to a branch the push output doesn't show",
     "rule": "Name the branch your git push output shows ('a -> b'), not the one you meant to push.",
     "why": "the push went to another ref"},
    {"id": "pushed.no_push", "kind": "pushed", "match": _why("no git push", "none to", "push output was not"),
     "title": "claims pushed without running git push",
     "rule": "Don't say you pushed unless `git push` ran in this turn; quote its 'branch -> branch' line.",
     "why": "no push ran in the turn the claim was made"},
    {"id": "merged.no_merge", "kind": "merged", "match": _why("no merge", "merge output was not"),
     "title": "claims merged without a merge in the turn",
     "rule": "Don't say a PR is merged unless you ran the merge (or read its merged state) in this turn; quote it.",
     "why": "no merge ran or was read in that turn"},
    {"id": "committed.no_commit", "kind": "committed", "match": _why("no git commit", "commit output was not",
                                                                     "sha differs"),
     "title": "claims committed without a matching git commit",
     "rule": "Don't say you committed unless git commit ran in this turn; quote the SHA it printed.",
     "why": "no commit with that SHA ran in the turn"},
    {"id": "pr_opened.no_pr", "kind": "pr_opened", "match": _why("no gh pr create", "different pr", "not conclusive"),
     "title": "claims a PR was opened without gh pr create",
     "rule": "Don't say a PR is open unless gh pr create ran in this turn; quote the PR URL it printed.",
     "why": "no PR was created in the turn"},
    {"id": "deployed.no_deploy", "kind": "deployed", "match": lambda r: True,
     "title": "claims deployed without a deploy command in the turn",
     "rule": "Don't say it's deployed unless the deploy command ran in this turn; quote its success line.",
     "why": "no deploy ran or it had no clear result"},
    {"id": "build.no_build", "kind": "build", "match": lambda r: True,
     "title": "claims the build passes without a fresh build",
     "rule": "Don't say the build passes unless you ran the build after your last edit; quote its result.",
     "why": "no build after the last edit, or its exit code was hidden"},
    {"id": "ci.unchecked", "kind": "ci", "match": lambda r: True,
     "title": "claims CI is green without reading the checks",
     "rule": "Don't say CI passes unless you read the checks in this turn (gh pr checks) and they're all done.",
     "why": "the checks weren't read, or were still pending"},
    {"id": "url.unchecked", "kind": "url", "match": lambda r: True,
     "title": "claims a URL is live without fetching it",
     "rule": "Before you say a URL is live, fetch it in this turn and quote the HTTP status.",
     "why": "the URL wasn't fetched, or returned another status"},
    {"id": "file.not_written", "kind": "file", "match": lambda r: True,
     "title": "claims a file was written without a write to it",
     "rule": "Only say you created or updated a file after a write to that exact path succeeded in this turn.",
     "why": "no successful write to that path in the turn"},
    {"id": "sha.unseen", "kind": "sha", "match": lambda r: True,
     "title": "quotes a commit SHA no tool output shows",
     "rule": "Copy SHAs from tool output in this turn (git rev-parse HEAD); never retype or guess them.",
     "why": "the SHA wasn't in any output"},
    {"id": "number.unseen", "kind": "number", "match": lambda r: True,
     "title": "quotes a count no tool output shows",
     "rule": "Only quote counts (files, lines, items) that a tool output in this turn shows.",
     "why": "the number wasn't in any output"},
]
BY_ID = {p["id"]: p for p in PATTERNS}
PROPOSAL_ID_RE = re.compile(r"^cc-[0-9a-f]{6}$")
_SKILL_JUNK = re.compile(r"[^\w.:@/+-]")


def safe_skill(name: Any) -> str:
    """A skill name as an identifier, or "" for anything else: a name with spaces, newlines or markup is dropped
    (not cleaned up), so a skill name can't carry an instruction into a coach rule, a handoff or the Cap Board."""
    name = name.strip() if isinstance(name, str) else ""
    return name[:80] if name and not _SKILL_JUNK.search(name) else ""


def trusted_rule(prop: Dict[str, Any]) -> Optional[str]:
    """The rule text a proposal may inject: always the library's own text for its pattern, never the text stored in
    coach.json (a file the agent can write). None for an unknown pattern or a malformed id."""
    p = BY_ID.get(str(prop.get("pattern") or ""))
    if p is None or not PROPOSAL_ID_RE.match(str(prop.get("id") or "")):
        return None
    return p["rule"]


def classify(r: Dict[str, Any]) -> Optional[str]:
    """The pattern id of one open receipt (🧢 or 🤔), or None for a proven one or an unknown kind."""
    if r.get("verdict") not in (CAP, NO_RECEIPT):
        return None
    # "3 tests still fail" is not a pass claim: only a count no run shows can make it a pattern (final dogfood)
    admits_failure = r.get("kind") == "tests" and bool((r.get("claim") or {}).get("fails"))
    for p in PATTERNS:
        if admits_failure and p["id"] != "tests.count_mismatch":
            continue
        if p["kind"] == r.get("kind") and p["match"](r):
            return p["id"]
    return None


RUNNERS = [("pytest", r"\bpytest\b"), ("node --test", r"\bnode\s+--test\b"), ("npm test", r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test"),
           ("jest", r"\bjest\b"), ("vitest", r"\bvitest\b"), ("cargo test", r"\bcargo\s+test"),
           ("go test", r"\bgo\s+test"), ("unittest", r"\bunittest\b"), ("git push", r"\bgit\s+push"),
           ("gh", r"\bgh\s"), ("git", r"\bgit\s")]


def runner_of(r: Dict[str, Any]) -> str:
    cmd = r.get("cmd") or ""
    for name, rx in RUNNERS:
        if re.search(rx, cmd):
            return name
    return r.get("tool") or "-"


def _skill(rec: Dict[str, Any]) -> str:
    skills = rec.get("skills") or []
    return str(skills[-1]) if skills else ANY


def scored(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("type", "reply") == "reply" and r.get("receipts")]


def _short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _claim_words(r: Dict[str, Any]) -> str:
    return (r.get("claim") or {}).get("frag") or r.get("text") or ""


# ---- 1) pattern miner -------------------------------------------------------------------------------------------
def mine(records: Iterable[Dict[str, Any]], since: float = 0.0) -> List[Dict[str, Any]]:
    """Cluster open receipts by (pattern, model, skill). One reply counts once per pattern (two 'tests pass'
    sentences in the same unproven reply are one cap, not two). Examples are redacted and truncated."""
    recs = [r for r in scored(records) if float(r.get("ts", 0) or 0) >= since]
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    scope_n: Counter = Counter()
    for rec in recs:
        model, skill = str(rec.get("model") or "unknown"), _skill(rec)
        kinds = {x.get("kind") for x in rec["receipts"]}
        for k in kinds:
            scope_n[(k, model, skill)] += 1
        seen = set()
        for x in rec["receipts"]:
            pid = classify(x)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            g = groups.setdefault((pid, model, skill), {
                "pattern": pid, "kind": BY_ID[pid]["kind"], "title": BY_ID[pid]["title"], "model": model,
                "skill": skill, "count": 0, "caps": 0, "no_receipts": 0, "runners": Counter(), "examples": [],
                "first_ts": rec.get("ts"), "last_ts": rec.get("ts")})
            g["count"] += 1
            g["caps" if x.get("verdict") == CAP else "no_receipts"] += 1
            g["runners"][runner_of(x)] += 1
            g["last_ts"] = rec.get("ts")
            if len(g["examples"]) < EXAMPLES:
                g["examples"].append({"claim": redact(_short(_claim_words(x), 120)),
                                      "why": _short(x.get("why") or ("contradicted: " + (x.get("quote") or "")), 120),
                                      "cmd": redact(_short(x.get("cmd") or "", 80)),
                                      "verdict": x.get("verdict"), "session": str(rec.get("session_id") or "")[:12]})
    out = []
    for (pid, model, skill), g in groups.items():
        g["replies_in_scope"] = scope_n[(g["kind"], model, skill)]
        g["rate"] = g["count"] / g["replies_in_scope"] if g["replies_in_scope"] else 0.0
        g["runners"] = dict(g["runners"].most_common())
        out.append(g)
    out.sort(key=lambda g: (-g["count"], -g["caps"], g["pattern"], g["model"], g["skill"]))
    return out


# ---- 2) fix generator -------------------------------------------------------------------------------------------
def proposal_id(pid: str, model: str, skill: str, agent: str) -> str:
    return "cc-" + hashlib.sha1(f"{agent}|{pid}|{model}|{skill}".encode(), usedforsecurity=False).hexdigest()[:6]


def marker(pid_or_id: str) -> str:
    return f"(No Cap coach {pid_or_id})"


def generate(pattern: Dict[str, Any], agent: str = "default", skills_dir: Optional[Path] = None) -> Dict[str, Any]:
    """A pattern → a proposal: a coach rule (default path) plus a skill-patch diff and a memory-note variant."""
    p = BY_ID[pattern["pattern"]]
    pid = proposal_id(p["id"], pattern["model"], pattern["skill"], agent)
    evidence = (f"{pattern['count']} of {pattern['replies_in_scope']} replies with a {p['kind']} claim "
                f"({pattern['caps']} 🧢, {pattern['no_receipts']} 🤔)")
    why = f"{p['why'].capitalize()}. Evidence: {evidence}."
    note = f"{p['rule']} {marker(pid)}"
    variants: Dict[str, Any] = {"rule": {"text": p["rule"]}, "memory": {"text": note, "target": "memory"}}
    skill = pattern["skill"]
    if skill != ANY:
        variants["skill"] = skill_patch(skill, pid, p["rule"], p["why"], skills_dir)
    return {"id": pid, "pattern": p["id"], "title": p["title"], "kind": p["kind"],
            "scope": {"agent": agent, "model": pattern["model"], "skill": skill},
            "rule": p["rule"], "why": why, "evidence": {k: pattern[k] for k in (
                "count", "caps", "no_receipts", "replies_in_scope", "rate", "runners", "examples")},
            "variants": variants}


def find_skill(skills_dir: Optional[Path], name: str) -> Optional[Path]:
    if not skills_dir or not name or not Path(skills_dir).is_dir():
        return None
    safe = re.sub(r"[^A-Za-z0-9_.:-]", "", name).split(":")[-1]
    for p in sorted(Path(skills_dir).glob(f"**/{safe}/SKILL.md")):
        return p
    return None


def skill_section(pid: str, rule: str, why: str) -> str:
    return f"\n## Receipts {marker(pid)}\n\n- {rule}\n  Why: {why}.\n"


def skill_patch(skill: str, pid: str, rule: str, why: str, skills_dir: Optional[Path]) -> Dict[str, Any]:
    """The exact unified diff that appends one section to the skill's SKILL.md. Never written by No Cap."""
    section = skill_section(pid, rule, why)
    path = find_skill(skills_dir, skill)
    if path is None:
        return {"skill": skill, "path": None, "section": section, "diff": "",
                "note": f"skill '{skill}' not found under {skills_dir}; the section is shown as text"}
    old = path.read_text(encoding="utf-8", errors="replace")
    new = old.rstrip("\n") + "\n" + section
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=f"a/{path.name}", tofile=f"b/{path.name}"))
    return {"skill": skill, "path": str(path), "section": section, "diff": diff}


# ---- 3) measurement ---------------------------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.959964) -> Tuple[float, float]:
    """Wilson score interval for k successes in n trials (95% by default). n=0 → (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def two_proportion(k1: int, n1: int, k2: int, n2: int) -> Dict[str, Any]:
    """Pooled two-proportion z-test, two-sided. Returns z and p (p=1 when undefined)."""
    if n1 <= 0 or n2 <= 0:
        return {"z": 0.0, "p": 1.0}
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"z": 0.0, "p": 1.0}
    z = (k1 / n1 - k2 / n2) / se
    return {"z": z, "p": math.erfc(abs(z) / math.sqrt(2))}


def mcnemar(b: int, c: int) -> Dict[str, Any]:
    """Exact McNemar test (two-sided binomial on the discordant pairs b, c)."""
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return {"b": b, "c": c, "p": min(1.0, 2 * tail)}


def in_scope(rec: Dict[str, Any], scope: Dict[str, Any], kind: str) -> bool:
    if scope.get("model", ANY) not in (ANY, "") and not fnmatch.fnmatch(str(rec.get("model") or ""), scope["model"]):
        return False
    if scope.get("skill", ANY) not in (ANY, "") and scope["skill"] not in (rec.get("skills") or []):
        return False
    return any(x.get("kind") == kind for x in rec.get("receipts", []))


def tally(records: Iterable[Dict[str, Any]], pattern: str, scope: Dict[str, Any], start: float,
          end: float = float("inf")) -> Dict[str, int]:
    kind = BY_ID[pattern]["kind"]
    n = k = 0
    for rec in scored(records):
        ts = float(rec.get("ts", 0) or 0)
        if not (start <= ts < end) or not in_scope(rec, scope, kind):
            continue
        n += 1
        if any(classify(x) == pattern for x in rec["receipts"]):
            k += 1
    return {"n": n, "k": k}


def measure(prop: Dict[str, Any], records: List[Dict[str, Any]], min_sample: int,
            now: Optional[float] = None) -> Dict[str, Any]:
    """Before (frozen at approval) vs after (live, up to revert). Rates only when both sides reach min_sample."""
    now = time.time() if now is None else now
    before = prop.get("baseline") or {"n": 0, "k": 0}
    start = float(prop.get("approved_ts") or now)
    end = float(prop.get("reverted_ts") or float("inf"))
    after = tally(records, prop["pattern"], prop["scope"], start, end)
    out = {"before": dict(before), "after": after, "min_sample": min_sample}
    for side in ("before", "after"):
        s = out[side]
        s["rate"] = s["k"] / s["n"] if s["n"] else None
        s["ci"] = wilson(s["k"], s["n"]) if s["n"] else None
    out["enough"] = before["n"] >= min_sample and after["n"] >= min_sample
    out["test"] = two_proportion(before["k"], before["n"], after["k"], after["n"]) if out["enough"] else None
    return out


def fmt_side(s: Dict[str, Any]) -> str:
    if not s["n"]:
        return "n=0"
    lo, hi = s["ci"]
    return f"{s['k']}/{s['n']} = {s['rate']:.0%} (95% CI {lo:.0%}–{hi:.0%})"


def fmt_measure(m: Dict[str, Any]) -> str:
    b, a = m["before"], m["after"]
    line = f"before {fmt_side(b)} → after {fmt_side(a)}"
    if not m["enough"]:
        need = [f"{side} n={m[side]['n']}" for side in ("before", "after") if m[side]["n"] < m["min_sample"]]
        return line + f" · not enough data yet ({', '.join(need)}; need {m['min_sample']} each)"
    t = m["test"]
    delta = a["rate"] - b["rate"]
    verdict = "better" if delta < 0 and t["p"] < 0.05 else "worse" if delta > 0 and t["p"] < 0.05 else "no clear change"
    return line + f" · {delta * 100:+.0f} pts, two-proportion p={t['p']:.3f} ({verdict})"


# ---- persistence ------------------------------------------------------------------------------------------------
class CoachStore:
    """coach.json in the plugin's data dir (0600). A corrupt file is set aside, never trusted or crashed on."""

    def __init__(self, data_dir: Callable[[], Path]):
        self._dir = data_dir
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return Path(self._dir()) / FILE

    def load(self) -> Dict[str, Any]:
        p = self.path
        if not p.exists():
            return {"proposals": {}}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("proposals"), dict):
                return data
        except Exception:
            pass
        try:
            os.replace(p, p.with_suffix(".corrupt"))
        except OSError:
            pass
        return {"proposals": {}}

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            p = self.path
            p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1, default=str)
            os.replace(tmp, p)


# ---- the coach --------------------------------------------------------------------------------------------------
class Coach:
    def __init__(self, data_dir: Callable[[], Path], setting: Callable[[str, Any], Any],
                 records: Callable[[], List[Dict[str, Any]]], home: Callable[[], Path],
                 inject: Optional[Callable[..., bool]] = None):
        self.store = CoachStore(data_dir)
        self.setting = setting
        self.records = records
        self.home = home
        self.inject = inject
        self._announced: set = set()
        self._lock = threading.Lock()
        self._skills: "OrderedDict[str, List[str]]" = OrderedDict()  # session → skills it loaded (injection scope)
        self._coached: Dict[str, List[str]] = {}  # session → rule ids injected into its current turn

    # -- engine hooks (the engine calls only these four, so engine.py stays a thin hook) --
    def note_tool(self, tool_name: str, args: Any, session_id: str) -> None:
        """post_tool_call: remember the skills this session loaded, so a skill-scoped rule is injected next turn."""
        if tool_name != "skill_view" or not isinstance(args, dict) or not isinstance(args.get("name"), str):
            return
        name = safe_skill(args["name"].strip())
        if not name:
            return
        with self._lock:
            names = self._skills.setdefault(session_id or "", [])
            self._skills.move_to_end(session_id or "")
            if name in names:
                names.remove(name)
            names.append(name)
            del names[:-8]
            while len(self._skills) > MAX_SESSIONS:
                self._skills.popitem(last=False)

    def session_skills(self, session_id: str) -> List[str]:
        with self._lock:
            return list(self._skills.get(session_id or "", []))

    def on_turn_start(self, session_id: str = "", model: str = "", **_: Any) -> Optional[Dict[str, str]]:
        """pre_llm_call: inject the approved coach rules that match this agent, model and loaded skills."""
        text, ids = self.context(model or "", self.session_skills(session_id or ""))
        with self._lock:
            self._coached[session_id or ""] = ids
            while len(self._coached) > MAX_SESSIONS:
                self._coached.pop(next(iter(self._coached)))
        return {"context": text} if text else None

    def take_coached(self, session_id: str) -> List[str]:
        """The rule ids injected into this session's current turn (stored on the reply record as `coach`)."""
        with self._lock:
            return self._coached.pop(session_id or "", [])

    def add_tip(self, notes: Optional[List[str]], receipts: List[Dict[str, Any]]) -> Optional[List[str]]:
        """transform_llm_output: append the auto-suggest line, if any. Never raises: the coach can't touch a reply."""
        try:
            tip = self.maybe_announce(receipts) if receipts else None
        except Exception:
            tip = None
        return (list(notes or []) + [tip]) if tip else notes

    def cfg(self) -> Dict[str, Any]:
        return settings(self.setting)

    def agent(self) -> str:
        try:
            h = Path(self.home())
            return h.name if h.parent.name == "profiles" else "default"
        except Exception:
            return "default"

    def skills_dir(self) -> Optional[Path]:
        try:
            return Path(self.home()) / "skills"
        except Exception:
            return None

    # -- mining + proposals --
    def scan(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Mine the store and refresh proposals for every pattern with at least min_evidence caps. Approved,
        reverted and dismissed proposals keep their status; only drafts get their evidence refreshed."""
        cfg = self.cfg()
        now = time.time() if now is None else now
        data = self.store.load()
        props = data["proposals"]
        fresh = []
        for g in mine(self.records()):
            if g["count"] < cfg["min_evidence"]:
                continue
            prop = generate(g, self.agent(), self.skills_dir())
            old = props.get(prop["id"])
            if old and old.get("status") != "proposed":
                old["evidence_now"] = prop["evidence"]
                continue
            prop.update(status="proposed", created_ts=(old or {}).get("created_ts", now), updated_ts=now)
            props[prop["id"]] = prop
            fresh.append(prop)
        self.store.save(data)
        return fresh

    def get(self, pid: str) -> Optional[Dict[str, Any]]:
        props = self.store.load()["proposals"]
        if pid in props:
            return props[pid]
        hits = [p for k, p in props.items() if k.startswith(pid)] if len(pid) >= 4 else []
        return hits[0] if len(hits) == 1 else None

    def approve(self, pid: str, variant: str = "rule", session_key: str = "", apply: bool = False,
                now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        data = self.store.load()
        prop = data["proposals"].get(pid) or self.get(pid)
        if not prop:
            return f"No proposal {pid}. /cap coach lists them."
        prop = data["proposals"][prop["id"]]
        variant = variant or "rule"
        if variant not in prop["variants"]:
            return f"{prop['id']} has no {variant} variant (has: {', '.join(prop['variants'])})."
        cfg = self.cfg()
        if prop.get("status") != "approved":
            start = now - cfg["window_days"] * 86400
            prop["baseline"] = dict(tally(self.records(), prop["pattern"], prop["scope"], start, now),
                                    window_days=cfg["window_days"])
            prop["approved_ts"] = now
            prop.pop("reverted_ts", None)
        prop["status"] = "approved"
        prop["variant"] = variant
        msg = [f"✅ Approved {prop['id']} ({variant}): {prop['title']}.",
               f"Baseline frozen: {prop['baseline']['k']}/{prop['baseline']['n']} in-scope replies hit this pattern "
               f"in the last {prop['baseline'].get('window_days', cfg['window_days'])} days. /cap coach status tracks after."]
        if variant == "rule":
            msg.append(f"Coach rule is live for {_scope_text(prop['scope'])}, injected as turn context through "
                       f"pre_llm_call. Revert any time: /cap coach revert {prop['id']}")
        else:
            msg += self._handoff(prop, variant, session_key, apply, revert=False)
        self.store.save(data)
        return "\n".join(msg)

    def _handoff(self, prop: Dict[str, Any], variant: str, session_key: str, apply: bool, revert: bool) -> List[str]:
        """A skill patch or memory note: show it, and (only when asked) ask the agent to apply it with its own tools."""
        v = dict(prop["variants"][variant])
        rule = trusted_rule(prop)
        if rule is None:
            return ["This proposal doesn't match a No Cap pattern (coach.json was edited by hand), so No Cap won't "
                    "pass it to the agent."]
        # the text handed to the agent is rebuilt from the library, never taken from coach.json
        v["skill"] = safe_skill(v.get("skill")) or "?"
        v["section"] = skill_section(prop["id"], rule, BY_ID[prop["pattern"]]["why"])
        v["text"] = f"{rule} {marker(prop['id'])}"
        if variant == "skill":
            where = v.get("path") or f"skill '{v['skill']}'"
            text = v.get("diff") or v["section"]
            if revert:
                ask = (f"[No Cap coach] The user reverted coach patch {prop['id']}. Remove the section headed "
                       f"'## Receipts {marker(prop['id'])}' from the {v['skill']} skill with skill_manage (patch). "
                       f"If you decline, say so plainly.")
            else:
                ask = (f"[No Cap coach] The user approved this patch to the {v['skill']} skill ({prop['id']}). "
                       f"Apply it with skill_manage (action=patch, name={v['skill']}): append exactly this section "
                       f"to SKILL.md, nothing else:\n{v['section']}\nIf you decline, say so plainly.")
        else:
            where = "memory (MEMORY.md)"
            text = v["text"]
            ask = (f"[No Cap coach] The user {'reverted' if revert else 'approved'} this memory note ({prop['id']}). "
                   + (f"Remove the entry containing '{marker(prop['id'])}' with your memory tool (remove)."
                      if revert else f"Save it with your memory tool (action=add, target=memory), verbatim:\n{text}")
                   + "\nIf you decline, say so plainly.")
        prop[f"{variant}_{'revert' if revert else 'apply'}_requested"] = False
        if apply and self.inject is not None:
            ok = False
            try:
                ok = bool(self.inject(ask, session_key))
            except Exception:
                ok = False
            if ok:
                prop[f"{variant}_{'revert' if revert else 'apply'}_requested"] = True
                return [f"Asked the agent to {'undo' if revert else 'apply'} it in {where} with its own tools. "
                        f"It may decline; /cap coach status checks the file."]
            return [f"Hermes didn't let No Cap message the agent from here. Apply it yourself in {where}:", text]
        return [f"No Cap doesn't edit {where}. To {'undo' if revert else 'apply'} it: edit it yourself, or re-run with "
                f"--apply to have the agent do it with its own tools:", text]

    def revert(self, pid: str, session_key: str = "", apply: bool = False, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        data = self.store.load()
        prop = self.get(pid)
        if not prop:
            return f"No proposal {pid}. /cap coach lists them."
        prop = data["proposals"][prop["id"]]
        if prop.get("status") != "approved":
            return f"{prop['id']} isn't active (status: {prop.get('status')}). Nothing to revert."
        prop["status"] = "reverted"
        prop["reverted_ts"] = now
        msg = [f"↩️ Reverted {prop['id']}: the coach rule is no longer injected. Its before/after record is kept."]
        if prop.get("variant") in ("skill", "memory"):
            msg += self._handoff(prop, prop["variant"], session_key, apply, revert=True)
        self.store.save(data)
        return "\n".join(msg)

    def dismiss(self, pid: str) -> str:
        data = self.store.load()
        prop = self.get(pid)
        if not prop:
            return f"No proposal {pid}."
        data["proposals"][prop["id"]]["status"] = "dismissed"
        self.store.save(data)
        return f"🗑️ Dismissed {prop['id']}. A rescan won't re-propose it."

    # -- injection --
    def active_rules(self, model: str = "", skills: Iterable[str] = ()) -> List[Dict[str, Any]]:
        cfg = self.cfg()
        if cfg["mode"] == "off":
            return []
        skills = set(skills or ())
        out = []
        for prop in self.store.load()["proposals"].values():
            if prop.get("status") != "approved" or prop.get("variant", "rule") != "rule" or not trusted_rule(prop):
                continue
            sc = prop.get("scope") or {}
            if sc.get("agent", "default") not in (ANY, self.agent()):
                continue
            if sc.get("model", ANY) not in (ANY, "") and not fnmatch.fnmatch(model or "", sc["model"]):
                continue
            if sc.get("skill", ANY) not in (ANY, "") and sc["skill"] not in skills:
                continue
            out.append(prop)
        out.sort(key=lambda p: p.get("approved_ts", 0))
        return out[: cfg["max_rules"]]

    def context(self, model: str = "", skills: Iterable[str] = ()) -> Tuple[Optional[str], List[str]]:
        rules = self.active_rules(model, skills)
        if not rules:
            return None, []
        lines = ["[No Cap coach: rules the user approved for this agent. They come from this agent's own past "
                 "unproven claims. /cap coach rules lists them.]"]
        lines += [f"- {trusted_rule(p)} ({p['id']})" for p in rules]
        return "\n".join(lines), [p["id"] for p in rules]

    # -- auto-suggest --
    def maybe_announce(self, receipts: List[Dict[str, Any]]) -> Optional[str]:
        """auto mode: one footer line the first time a pattern reaches auto_after_caps. Never applies anything."""
        cfg = self.cfg()
        if cfg["mode"] != "auto" or not any(classify(r) for r in receipts):
            return None
        threshold = max(cfg["auto_after_caps"], 1)
        data = self.store.load()
        announced = set(data.get("announced") or [])
        for g in mine(self.records()):
            if g["count"] < threshold:
                continue
            pid = proposal_id(g["pattern"], g["model"], g["skill"], self.agent())
            if pid in announced or pid in self._announced:
                continue
            prop = data["proposals"].get(pid)
            if prop and prop.get("status") in ("approved", "dismissed", "reverted"):
                continue
            if not prop:
                prop = dict(generate(g, self.agent(), self.skills_dir()), status="proposed",
                            created_ts=time.time(), updated_ts=time.time())
                data["proposals"][pid] = prop
            announced.add(pid)
            self._announced.add(pid)
            data["announced"] = sorted(announced)
            self.store.save(data)
            return (f"🧢 Cap Coach: this agent {g['title']} ({g['count']}×). A fix is drafted, not applied: "
                    f"/cap coach show {pid}")
        return None

    # -- status --
    def file_state(self, prop: Dict[str, Any]) -> str:
        v = prop.get("variant")
        if v == "skill":
            path = (prop["variants"]["skill"] or {}).get("path")
            found = bool(path) and Path(path).exists() and marker(prop["id"]) in Path(path).read_text(
                encoding="utf-8", errors="replace")
        elif v == "memory":
            mem = Path(self.home()) / "memories"
            found = any(marker(prop["id"]) in f.read_text(encoding="utf-8", errors="replace")
                        for f in mem.glob("*.md")) if mem.is_dir() else False
        else:
            return ""
        want = prop.get("status") == "approved"
        if found == want:
            return "in place" if want else "removed"
        asked = prop.get(f"{v}_{'apply' if want else 'revert'}_requested")
        return ("not applied yet" if want else "still present") + (
            " (the agent was asked; it may have declined)" if asked else " (waiting for you to apply it)")

    def status(self) -> str:
        cfg = self.cfg()
        props = list(self.store.load()["proposals"].values())
        records = self.records()
        lines = [f"🧢 **Cap Coach** · mode {cfg['mode']} · propose at {cfg['min_evidence']} caps · "
                 f"before/after needs n≥{cfg['min_sample']} each"]
        live = [p for p in props if p.get("status") in ("approved", "reverted")]
        if not props:
            lines.append("No proposals yet. /cap coach scan mines the receipts store.")
        for p in sorted(live, key=lambda p: p.get("approved_ts", 0)):
            m = measure(p, records, cfg["min_sample"])
            state = self.file_state(p)
            lines.append(f"• {p['id']} [{p['status']}, {p.get('variant', 'rule')}] {p['title']} · "
                         f"{_scope_text(p['scope'])}" + (f" · {state}" if state else ""))
            lines.append(f"   {fmt_measure(m)}")
        drafts = [p for p in props if p.get("status") == "proposed"]
        for p in sorted(drafts, key=lambda p: -p["evidence"]["count"]):
            lines.append(f"• {p['id']} [draft] {p['title']} · {p['evidence']['count']}× · {_scope_text(p['scope'])}"
                         f" · /cap coach show {p['id']}")
        return "\n".join(lines)

    def show(self, pid: str) -> str:
        p = self.get(pid)
        if not p:
            return f"No proposal {pid}."
        e = p["evidence"]
        lines = [f"**{p['id']}** · {p['title']} · status {p.get('status')}",
                 f"Scope: {_scope_text(p['scope'])}",
                 f"Evidence: {e['count']} of {e['replies_in_scope']} in-scope replies ({e['rate']:.0%}); "
                 f"{e['caps']} 🧢 contradicted, {e['no_receipts']} 🤔 unbacked; runners: "
                 + ", ".join(f"{k} {v}" for k, v in e["runners"].items())]
        for x in e["examples"]:
            lines.append(f"  e.g. “{x['claim']}” → {x['why']}" + (f" · `{x['cmd']}`" if x["cmd"] else ""))
        lines += [f"Proposed coach rule: {p['rule']}", f"Why: {p['why']}",
                  f"Approve: /cap coach approve {p['id']}  (rule, injected via pre_llm_call, revertible)"]
        if "skill" in p["variants"]:
            v = p["variants"]["skill"]
            lines += [f"Or as a skill patch to '{v['skill']}': /cap coach approve {p['id']} skill [--apply]",
                      v.get("diff") or v["section"]]
        lines += [f"Or as a memory note: /cap coach approve {p['id']} memory [--apply]",
                  p["variants"]["memory"]["text"],
                  "Nothing is applied until you approve. --apply asks the agent to make the edit with its own tools."]
        return "\n".join(lines)

    def rules_text(self) -> str:
        props = [p for p in self.store.load()["proposals"].values() if p.get("status") == "approved"]
        if not props:
            return "No coach rules are active. Nothing is injected."
        lines = ["Active coach rules (injected through pre_llm_call as labelled turn context, only in scope):"]
        lines += [f"• {p['id']} [{p.get('variant', 'rule')}] {p['rule']} · {_scope_text(p['scope'])}" for p in props]
        return "\n".join(lines)

    # -- the /cap coach command --
    def command(self, args: List[str], session_key: str = "") -> str:
        cfg = self.cfg()
        sub = (args[0].lower() if args else "status")
        rest = args[1:]
        flags = {a for a in rest if a.startswith("--")}
        rest = [a for a in rest if not a.startswith("--")]
        if sub in ("help", "?"):
            return ("/cap coach → status · scan → mine receipts and draft fixes · show <id> · "
                    "approve <id> [rule|skill|memory] [--apply] · revert <id> [--apply] · dismiss <id> · rules")
        if cfg["mode"] == "off" and sub not in ("status", "rules", "revert"):
            return "Cap Coach is off (plugins.entries.no-cap.settings.coach.mode: off). No mining, no injection."
        if sub == "scan":
            fresh = self.scan()
            if not fresh:
                pats = mine(self.records())
                top = ", ".join(f"{g['title']} {g['count']}×" for g in pats[:3]) or "none"
                return (f"No pattern has {cfg['min_evidence']}+ caps yet (min_evidence). Top so far: {top}.")
            return "\n".join([f"Drafted {len(fresh)} fix(es); nothing applied:"] +
                             [f"• {p['id']} {p['title']} · {p['evidence']['count']}× · /cap coach show {p['id']}"
                              for p in fresh])
        if sub in ("show", "approve", "revert", "dismiss") and not rest:
            return f"Usage: /cap coach {sub} <id>"
        if sub == "show":
            return self.show(rest[0])
        if sub == "approve":
            return self.approve(rest[0], rest[1].lower() if len(rest) > 1 else "rule", session_key,
                                apply="--apply" in flags)
        if sub == "revert":
            return self.revert(rest[0], session_key, apply="--apply" in flags)
        if sub == "dismiss":
            return self.dismiss(rest[0])
        if sub == "rules":
            return self.rules_text()
        return self.status()


def _scope_text(scope: Dict[str, Any]) -> str:
    return (f"agent {scope.get('agent', 'default')} · model {scope.get('model', ANY)}"
            + (f" · skill {scope['skill']}" if scope.get("skill", ANY) != ANY else " · any skill"))
