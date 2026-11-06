"""Cross-turn receipts: the session ledger lets a claim about earlier work cite an earlier turn of the SAME session."""
import json
import os
import stat
import time

from nocap.engine import Engine
from nocap.store import MAX_SESSION_CALLS, MAX_SESSION_TURNS, Ledger
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT

PY_OK = "............................................ [100%]\n44 passed in 2.02s"
PY_FAIL = "....F\n1 failed, 43 passed in 2.31s"
PUSH = "To github.com:acme/shop.git\n * [new branch]      feat/login -> feat/login"


def engine(d, **settings):
    settings.setdefault("show_uncertain", "all")
    return Engine(lambda: d, lambda k, default=None: settings.get(k, default))


def term(e, sid, tid, cmd, out, code=0):
    e.on_tool(tool_name="terminal", args={"command": cmd}, result=json.dumps({"output": out, "exit_code": code}),
              session_id=sid, turn_id=tid)


def patch(e, sid, tid, path="src/app.py"):
    e.on_tool(tool_name="patch", args={"path": path, "old_string": "a", "new_string": "b"},
              result=json.dumps({"success": True}), session_id=sid, turn_id=tid)


def receipts(e, sid):
    return e.store.last(sid)["receipts"]


def say(e, sid, tid, text):
    return e.on_reply(response_text=text, session_id=sid, turn_id=tid, model="m", platform="cli")


def test_earlier_turn_receipt_says_turn_n(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_OK)
    term(e, "s", "t1", "git push -u origin feat/login", PUSH)
    say(e, "s", "t1", "Done.")
    out = say(e, "s", "t2", "Tests passed in the last turn, and I pushed that to feat/login earlier.")
    rs = receipts(e, "s")
    assert [(r["kind"], r["verdict"], r.get("turn"), r["cite"]) for r in rs] == [
        ("tests", NO_CAP, 1, 1), ("pushed", NO_CAP, 1, 2)]
    assert "turn 1 call 1 `pytest -q`" in out and "turn 1 call 2" in out


def test_code_edit_in_any_later_turn_makes_it_stale(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_OK)
    say(e, "s", "t1", "Done.")
    patch(e, "s", "t2")
    say(e, "s", "t2", "Edited it.")
    say(e, "s", "t3", "All tests passed earlier.")
    r = receipts(e, "s")[0]
    assert r["verdict"] == NO_RECEIPT and r["turn"] == 1 and "code changed" in r["why"]


def test_edit_in_this_turn_also_makes_it_stale(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_OK)
    say(e, "s", "t1", "Done.")
    patch(e, "s", "t2")
    say(e, "s", "t2", "Tests passed in the last turn.")
    assert receipts(e, "s")[0]["verdict"] == NO_RECEIPT


def test_cap_from_an_earlier_turn(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_FAIL, 1)
    say(e, "s", "t1", "Looking into it.")
    out = say(e, "s", "t2", "Tests passed in the last turn.")
    r = receipts(e, "s")[0]
    assert r["verdict"] == CAP and r["turn"] == 1 and "🧢 CAP" in out and "turn 1 call 1" in out


def test_later_evidence_supersedes_an_earlier_cap(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_FAIL, 1)
    say(e, "s", "t1", "Looking into it.")
    term(e, "s", "t2", "pytest -q", PY_OK)
    say(e, "s", "t2", "Fixed.")
    say(e, "s", "t3", "Tests passed in the last turn.")
    r = receipts(e, "s")[0]
    assert r["verdict"] == NO_CAP and r["turn"] == 2


def test_cap_needs_every_earlier_turn_to_agree(tmp_path):
    """A green run in turn 1 and a red one in turn 2: "tests passed earlier" may mean turn 1, so no 🧢."""
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_OK)
    say(e, "s", "t1", "Green.")
    term(e, "s", "t2", "pytest -q", PY_FAIL, 1)
    say(e, "s", "t2", "One broke.")
    say(e, "s", "t3", "The tests passed earlier.")
    assert receipts(e, "s")[0]["verdict"] != CAP


def test_present_tense_claim_is_not_judged_on_earlier_turns(tmp_path):
    """"All 44 tests pass" states the current state: the user may have changed things between turns."""
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_OK)
    say(e, "s", "t1", "Done.")
    say(e, "s", "t2", "All 44 tests pass.")
    r = receipts(e, "s")[0]
    assert r["verdict"] == NO_RECEIPT and not r.get("turn")


def test_other_sessions_are_never_evidence(tmp_path):
    e = engine(tmp_path)
    term(e, "a", "t1", "pytest -q", PY_OK)
    say(e, "a", "t1", "Done.")
    say(e, "b", "t1", "Tests passed in the last turn.")
    assert e.store.last("b") is None


def test_other_process_reads_the_ledger_file(tmp_path):
    e1 = engine(tmp_path)
    term(e1, "s", "t1", "git push -u origin feat/login", PUSH)
    say(e1, "s", "t1", "Done.")
    e2 = engine(tmp_path)  # a gateway and a CLI process share the store folder
    say(e2, "s", "t2", "I pushed it to feat/login earlier.")
    assert receipts(e2, "s")[0]["verdict"] == NO_CAP


def test_ledger_file_is_private_redacted_and_purged(tmp_path):
    e = engine(tmp_path)
    fake = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"  # built at run time: no secret-shaped literal in the repo
    term(e, "s", "t1", f"GITHUB_TOKEN={fake} pytest -q", PY_OK)
    say(e, "s", "t1", "Done.")
    p = tmp_path / "ledger.jsonl"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    text = p.read_text()
    assert "ghp_abcdefghij" not in text and "[redacted]" in text
    assert "44 passed in 2.02s" in text  # facts (the summary line) yes; the raw output never
    assert "............" not in text
    e.nocap("purge")
    assert not p.exists()
    say(e, "s", "t2", "Tests passed in the last turn.")
    assert e.store.last("s") is None  # the purged ledger is gone from memory too


def test_cross_turn_off(tmp_path):
    e = engine(tmp_path, cross_turn=False)
    term(e, "s", "t1", "pytest -q", PY_OK)
    say(e, "s", "t1", "Done.")
    say(e, "s", "t2", "Tests passed in the last turn.")
    assert e.store.last("s") is None
    assert not (tmp_path / "ledger.jsonl").exists()


def test_no_turn_id_is_never_recorded_or_capped(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "", "pytest -q", PY_FAIL, 1)
    say(e, "s", "", "Looking.")
    assert not (tmp_path / "ledger.jsonl").exists()


def test_replayed_turn_is_not_its_own_earlier_turn(tmp_path):
    e = engine(tmp_path)
    term(e, "s", "t1", "pytest -q", PY_FAIL, 1)
    say(e, "s", "t1", "Looking.")
    say(e, "s", "t1", "Tests passed in the last turn.")  # the host re-ran t1's reply hook
    assert e.store.last("s") is None


def test_ledger_is_capped_per_session(tmp_path):
    led = Ledger(lambda: tmp_path, lambda: 30)
    for n in range(1, MAX_SESSION_TURNS + 30):
        led.record("s", f"t{n}", n, [{"i": k, "tool": "terminal"} for k in range(1, 9)])
    h = led.history("s")
    assert len(h) <= MAX_SESSION_TURNS
    assert sum(len(t["calls"]) for t in h) <= MAX_SESSION_CALLS
    assert h[-1]["turn"] == MAX_SESSION_TURNS + 29  # numbering keeps counting
    fresh = Ledger(lambda: tmp_path, lambda: 30).history("s")  # same cap when read back from the file
    assert sum(len(t["calls"]) for t in fresh) <= MAX_SESSION_CALLS and fresh[-1]["turn"] == h[-1]["turn"]


def test_ledger_retention(tmp_path):
    led = Ledger(lambda: tmp_path, lambda: 1)
    old = {"type": "turn", "ts": time.time() - 3 * 86400, "session_id": "s", "turn_id": "t0", "turn": 1, "calls": []}
    (tmp_path / "ledger.jsonl").write_text(json.dumps(old) + "\n")
    assert led.history("s") == []
    led.record("s", "t2", 2, [])
    assert "t0" not in (tmp_path / "ledger.jsonl").read_text()  # pruned on the first write
