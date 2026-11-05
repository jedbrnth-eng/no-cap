"""The No Cap kernel: per-turn evidence ledger in, receipts out.

Every public entry point is called through the fail-open wrappers in the plugin's __init__.py, so an
exception here leaves the user's reply untouched and is logged.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import card, doctor, score
from .claims import extract_claims, forged_stamps
from .evidence import extract, summary
from .render import EMOJI, TAG, claim_text, compose, footer, receipt_line
from .store import Store
from .verdict import CAP, DEFAULT_SHOW_UNCERTAIN, NO_CAP, NO_RECEIPT, judge, level_of, shown
from .verify import recheck, suggestion
from . import board  # Cap Board: identity at hook time, /capscore board

MAX_OPEN_TURNS = 64
MAX_CALLS = 500
MODES = ("annotate", "strict", "quiet")
STRICT_KINDS = {"tests", "build", "ci", "pushed", "merged", "deployed", "url", "file", "committed", "pr_opened"}
MAX_STRICT_NUDGES = 2
SKILL_TOOLS = ("skill_view", "skill")  # a turn "used" a skill when it loaded one with these tools


def _match_key(r: Dict[str, Any]) -> Tuple:
    c = r.get("claim", {})
    field = {"pushed": "branch", "merged": "pr", "file": "path", "url": "url", "sha": "sha", "number": "value",
             "pr_opened": "pr", "committed": "sha"}.get(r["kind"])
    return (r["kind"], str(c.get(field)) if field else "")


def _cited(evs: List[Dict[str, Any]], receipts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Only the calls a receipt cites are stored (as evidence.summary facts); the rest of the turn is a count and a digest."""
    cited = {r.get("cite") for r in receipts if r.get("cite") is not None}
    return [summary(e) for e in evs if e.get("i") in cited][-20:]


def _ledger(evs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The whole turn as a count plus a SHA-256 over each call's tool name and argument digest (no commands)."""
    h = hashlib.sha256()
    for e in evs:
        h.update(f"{e.get('i')}|{e.get('tool')}|{e.get('digest')}|{e.get('exit')}\n".encode("utf-8", "replace"))
    return {"n": len(evs), "digest": "sha256:" + h.hexdigest()[:16]}


class Engine:
    def __init__(self, data_dir: Callable[[], Path], setting: Callable[[str, Any], Any],
                 inject: Optional[Callable[..., bool]] = None, cwd: Optional[Callable[[], str]] = None,
                 home: Optional[Callable[[], Path]] = None, entry: Optional[Callable[[], Dict[str, Any]]] = None,
                 enabled: Optional[Callable[[str], Any]] = None):
        self.home = home or (lambda: Path(data_dir()).parents[1])
        self.entry = entry or (lambda: {})
        self.enabled = enabled or (lambda name: None)
        self.setting = setting
        self.data_dir = data_dir
        self.inject = inject
        self.cwd = cwd or (lambda: "")
        self.profile = board.profile_name  # who this turn runs as, recorded with each reply for the Cap Board
        self.store = Store(data_dir, lambda: setting("retention_days", 30))
        self._turns: "OrderedDict[Tuple[str, str], List[Dict[str, Any]]]" = OrderedDict()
        self._pending_cap: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    # ---- hooks -------------------------------------------------------------------------------
    def on_tool(self, tool_name: str = "", args: Any = None, result: Any = None, session_id: str = "",
                turn_id: str = "", status: Optional[str] = None, error_message: Optional[str] = None,
                **_: Any) -> None:
        key = (session_id or "", turn_id or "")
        with self._lock:
            calls = self._turns.setdefault(key, [])
            self._turns.move_to_end(key)
            while len(self._turns) > MAX_OPEN_TURNS:
                self._turns.popitem(last=False)
            index = (calls[-1]["i"] + 1) if calls else 1
        ev = extract(tool_name, args, result, status=status, index=index, error_message=error_message)
        if str(tool_name or "") in SKILL_TOOLS and ev.get("ok") and isinstance(args, dict) \
                and isinstance(args.get("name"), str):  # a failed load (unknown skill) isn't a skill the turn used
            ev["skill"] = args["name"].strip()[:80]
        with self._lock:
            calls.append(ev)
            if len(calls) > MAX_CALLS:  # keep the newest calls: the latest run is the one that matters
                del calls[0]

    def _take(self, session_id: str, turn_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            for key in ((session_id, turn_id), (session_id, "")):
                if key in self._turns:
                    return self._turns.pop(key)
        return []

    def _peek(self, session_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            for key in reversed(list(self._turns)):
                if key[0] == session_id:
                    return list(self._turns[key])
        return []

    def on_verify(self, session_id: str = "", attempt: int = 0, final_response: str = "", **_: Any):
        """Strict mode on coding turns: keep the agent going until its claims have receipts (bounded)."""
        if self.mode() != "strict" or (attempt or 0) >= MAX_STRICT_NUDGES or not final_response:
            return None
        claims = extract_claims(final_response)
        receipts = judge(claims, self._peek(session_id or ""), kinds=STRICT_KINDS)
        open_ = [r for r in receipts if r["verdict"] != NO_CAP]
        if not open_:
            return None
        items = "\n".join(f"- {TAG[r['verdict']]} “{claim_text(r)[:120]}” ({r.get('quote') or r.get('why')}) → "
                          f"{suggestion(r, [])}" for r in open_[:6])
        return {"action": "continue", "message": "[No Cap strict] Before you finish, these claims have no receipt in "
                "this turn. Run the check and show it, or drop the claim:\n" + items}

    def mode(self) -> str:
        m = str(self.setting("mode", "annotate") or "annotate").lower()
        return m if m in MODES else "annotate"

    def show_uncertain(self) -> str:
        return level_of(self.setting("show_uncertain", DEFAULT_SHOW_UNCERTAIN))

    def on_reply(self, response_text: str = "", session_id: str = "", turn_id: str = "", model: str = "",
                 platform: str = "", **_: Any) -> Optional[str]:
        session_id, turn_id = session_id or "", turn_id or ""
        evs = self._take(session_id, turn_id)
        if not isinstance(response_text, str) or not response_text.strip():
            return None
        claims = extract_claims(response_text)
        if not bool(self.setting("check_numbers", True)):
            claims = [c for c in claims if c["kind"] != "number"]
        receipts = judge(claims, evs) if claims else []
        if not turn_id:  # no turn id: the evidence may belong to an earlier, interrupted turn, so never 🧢
            receipts = [dict(r, verdict=NO_RECEIPT, why="no turn id from the host; can't tie evidence to this reply")
                        if r["verdict"] == CAP else r for r in receipts]
        level = self.show_uncertain()
        receipts = [dict(r, hidden=not shown(r, level)) for r in receipts]
        visible = [r for r in receipts if not r["hidden"]]
        rescore = self._rescore(session_id, receipts)
        if receipts or evs or rescore:
            self.store.append({**self._who(evs), "type": "reply", "ts": time.time(), "session_id": session_id, "turn_id": turn_id,
                               "model": model or "unknown", "platform": platform or "", "mode": self.mode(),
                               "calls": _cited(evs, receipts), "ledger": _ledger(evs), "receipts": receipts,
                               "rescore": rescore})
        streak = None
        if visible:
            mine = [r for r in self.store.records() if r.get("session_id") == session_id]
            streak = score.streak(mine)
            if streak < 2:
                streak = None
        forged = forged_stamps(response_text)
        notes = [f"⚠️ This reply contained {forged} stamp(s) No Cap didn't issue. They were ignored."] if forged else None
        return compose(response_text, visible, self.mode(), rescore, streak, notes,
                       plain=(platform or "").lower() == "cli")

    def _who(self, evs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Cap Board identity: the Hermes profile and the skills loaded in this turn (fail open to unknown)."""
        try:
            profile = str(self.profile() or "")[:64]
        except Exception:
            profile = ""
        return {"profile": profile, "skills": sorted({e["skill"] for e in evs if e.get("skill")})}

    def _rescore(self, session_id: str, receipts: List[Dict[str, Any]]) -> List[str]:
        with self._lock:
            pending = self._pending_cap.pop(session_id, None)
        if not pending:  # /cap may have run in another process (gateway vs CLI): read it from the store
            for rec in reversed(self.store.records()):
                if rec.get("session_id") != session_id or rec.get("type") == "recheck":
                    continue
                if rec.get("type") == "cap":
                    pending = rec.get("receipts") or []
                break
        if not pending:
            return []
        now = {_match_key(r): r for r in receipts}
        now_kind = {}
        for r in receipts:
            now_kind.setdefault(r["kind"], r)
        lines = []
        for old in pending:
            new = now.get(_match_key(old)) or (now_kind.get(old["kind"]) if old["kind"] in
                                               ("tests", "ci", "build", "deployed") else None)
            was = EMOJI[old["verdict"]]
            what = f"“{claim_text(old)[:50]}” ({old['kind']})"  # one sentence can hold two claims: name the kind
            if new is None:
                lines.append(f"🔁 /cap re-score: {was} → 🫡 retracted {what}")
            elif new["verdict"] == NO_CAP:
                lines.append(f"🔁 /cap re-score: {was} → 🧾 {what} now has a receipt")
            else:
                lines.append(f"🔁 /cap re-score: still {EMOJI[new['verdict']]} {what}")
        return lines

    # ---- commands ----------------------------------------------------------------------------
    def cap(self, raw_args: str = "", session_id: str = "", session_key: str = "") -> str:
        last = self.store.last(session_id or "")
        open_ = [r for r in (last or {}).get("receipts", []) if r["verdict"] in (CAP, NO_RECEIPT)]
        if not last or not open_:
            return "🧾 Nothing to cap: the last reply had no unproven claims."
        cwd = ""
        try:
            cwd = self.cwd() or ""
        except Exception:
            cwd = ""
        allow_http = bool(self.setting("self_verify_http", False))
        flipped, remaining = [], []
        for r in open_:
            res = recheck(r, cwd, allow_http)
            if res and res[0] != r["verdict"]:
                r2 = dict(r, verdict=res[0], verified=res[1], was=r["verdict"])
                (flipped if res[0] == NO_CAP else remaining).append(r2)
            else:
                remaining.append(r)
        self.store.append({"type": "recheck", "ts": time.time(), "session_id": session_id,
                           "receipts": flipped + remaining})
        lines = []
        for r in flipped:
            lines.append(f"🔍 Checked it myself: {EMOJI[r['was']]} → {EMOJI[r['verdict']]} “{claim_text(r)[:50]}” · {r['verified']}")
        if not remaining:
            lines.append("🧾 No cap after all: every claim has a receipt now.")
            return "\n".join(lines)
        test_cmds = [c["cmd"] for rec in self.store.records() if rec.get("session_id") == session_id
                     for c in rec.get("calls", []) if c.get("test_cmd") and c.get("cmd")]
        steer = self._steer(remaining, test_cmds)
        with self._lock:
            self._pending_cap[session_id or ""] = remaining
        self.store.append({"type": "cap", "ts": time.time(), "session_id": session_id, "receipts": remaining})
        ok = False
        if self.inject is not None:
            try:
                ok = bool(self.inject(steer, session_key))
            except Exception:
                ok = False
        if ok:
            lines.append(f"🧢 Cap called on {len(remaining)} claim(s). The agent has to show receipts or take "
                         f"them back; the next reply gets re-scored.")
        else:
            lines.append("🧢 Cap called. Hermes didn't let No Cap send the steer from here (gateway-backed sessions, "
                         "which on current Hermes includes the classic CLI, need "
                         "`plugins.entries.no-cap.allow_gateway_injection: true`). Paste this as your next message "
                         "and the reply gets re-scored:\n\n" + steer)
        return "\n".join(lines)

    @staticmethod
    def _steer(remaining: List[Dict[str, Any]], test_cmds: List[str]) -> str:
        out = ["[No Cap] I'm calling cap on these claims from your last reply. For each one, run the check "
               "now and show the output, or retract it in plain words. Don't restate it without proof."]
        for i, r in enumerate(remaining, 1):
            why = r.get("quote") if r["verdict"] == CAP else (r.get("why") or "no receipt")
            claim = claim_text(r)[:160].replace("`", "'")  # the agent's own words, quoted, never as a command
            out.append(f"{i}. {TAG[r['verdict']]} your reply said “{claim}” ({why}) → {suggestion(r, test_cmds)}")
        return "\n".join(out)

    def capscore(self, raw_args: str = "", session_id: str = "", platform: str = "") -> str:
        arg = (raw_args or "").strip().lower()
        if arg in ("board", "team"):
            # Own profile only unless board.team_profiles opts in AND this is the CLI (never a gateway chat).
            srcs, scope = board.scoped_sources(team=self.setting("board.team_profiles", None), platform=platform,
                                               extra=self.board_sources())
            b = board.build_board(srcs, min_claims=self.board_min_claims())
            b["scope"] = scope
            return board.board_text(b)
        records = self.store.records()
        if arg in ("card", "image", "png", "share"):
            rows = score.table(records)
            mine = [r for r in score.scored(records) if r.get("session_id") == session_id]
            paths = card.render(rows, Path(self.data_dir()), model=mine[-1].get("model") if mine else None)
            if not paths:
                return "🧾 Cap Score: no checked replies yet, so there's no card to make."
            return "🖼️ Scorecard saved: " + " · ".join(str(p) for p in paths)
        return score.leaderboard_text(records, session_id)

    def board_sources(self) -> List[Any]:
        extra = board.env_sources()
        extra += board.parse_sources(self.setting("board_sources", "") or "")
        return extra

    def board_min_claims(self) -> int:
        try:
            return max(1, int(self.setting("board_min_claims", board.MIN_CLAIMS) or board.MIN_CLAIMS))
        except (TypeError, ValueError):
            return board.MIN_CLAIMS

    def doctor_report(self) -> Tuple[str, int]:
        return doctor.check(Path(self.home()), self.mode(), self.entry() or {}, self.store.path, self.store.records(),
                            self.enabled, show_uncertain=self.show_uncertain())

    def nocap(self, raw_args: str = "", session_id: str = "") -> str:
        arg = (raw_args or "").strip().lower()
        if arg == "purge":
            n = self.store.purge()
            return f"🧹 Removed {n} receipt record(s) and the scorecard from {self.data_dir()}."
        if arg == "doctor":
            return self.doctor_report()[0]
        if arg in ("help", "?"):
            return ("/nocap → receipts for the last reply · /nocap all → every receipt line · /nocap purge → delete "
                    "the local store · /nocap doctor → setup checks · /cap → make the agent prove it · /capscore [card] → honesty leaderboard")
        last = self.store.last(session_id or "") or self.store.last("")
        if not last:
            return f"🧾 No receipts yet. Mode: {self.mode()}. Store: {self.store.path}"
        rs = last["receipts"]
        quiet = [r for r in rs if r.get("hidden")]
        if arg == "all":
            lines = ["**Receipts** (all)"] + [receipt_line(r) + (" · (not stamped: unsure)" if r.get("hidden") else "")
                                             for r in rs]
        else:
            lines = [footer([r for r in rs if not r.get("hidden")], last.get("rescore")) or "**Receipts**"]
            if quiet:
                lines.append(f"🤫 {len(quiet)} unsure claim(s) not stamped (show_uncertain: {self.show_uncertain()})"
                             " · /nocap all to see them · /cap still checks them")
        if last.get("calls") or last.get("ledger"):
            n = (last.get("ledger") or {}).get("n", len(last.get("calls") or []))
            cited = " · ".join(f"{c['i']}:{c['tool']}" + (f"(exit {c['exit']})" if c.get("exit") is not None else "")
                               for c in (last.get("calls") or [])[-12:])
            lines.append(f"Ledger: {n} tool call(s)" + (f"; cited {cited}" if cited else ""))
        lines.append(f"Mode: {self.mode()} · model: {last.get('model')} · store: {self.store.path}")
        return "\n".join(lines)
