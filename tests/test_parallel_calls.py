"""Parallel tool calls: Hermes runs a batch of tool calls on worker threads and each worker reports its own result,
so post_tool_call arrives concurrently and out of order. Every call still needs its own number, and the turn's
ledger has to stay in the order the results arrived: receipts cite "call N", and "the latest run" is decided by N.
"""
import json
import threading

from nocap import engine as engine_mod
from nocap.engine import Engine

PY_FAIL = "FAILED tests/test_a.py::test_x - AssertionError\n3 failed, 41 passed in 0.61s"


def make(tmp_path):
    settings = {"show_uncertain": "all", "verify_artifacts": False}
    return Engine(lambda: tmp_path / "data", lambda k, default=None: settings.get(k, default))


def term(eng, cmd, output, exit_code=0):
    eng.on_tool(tool_name="terminal", args={"command": cmd},
                result=json.dumps({"output": output, "exit_code": exit_code}), session_id="s", turn_id="t", status="ok")


def slow_first_call(monkeypatch):
    """Make the extraction of the command `slow` wait until released: a big output parsed on one worker while the
    other workers of the batch report theirs."""
    release, started = threading.Event(), threading.Event()
    real = engine_mod.extract

    def extract(tool_name, args, result, **kw):
        if isinstance(args, dict) and args.get("command") == "slow":
            started.set()
            assert release.wait(10)
        return real(tool_name, args, result, **kw)

    monkeypatch.setattr(engine_mod, "extract", extract)
    return release, started


def batch_with_a_slow_call(eng, monkeypatch, others):
    """One worker's result is still being parsed while `others` report; then it lands."""
    release, started = slow_first_call(monkeypatch)
    worker = threading.Thread(target=term, args=(eng, "slow", "ok"))
    worker.start()
    assert started.wait(10)
    for call in others:
        call()
    release.set()
    worker.join(10)
    assert not worker.is_alive()


def test_every_call_of_a_parallel_batch_gets_its_own_number(tmp_path, monkeypatch):
    eng = make(tmp_path)
    batch_with_a_slow_call(eng, monkeypatch, [lambda: term(eng, "ls a", "a"), lambda: term(eng, "ls b", "b")])
    term(eng, "ls c", "c")  # the next, sequential call
    calls = eng._peek("s")
    assert sorted(e["i"] for e in calls) == [1, 2, 3, 4]
    assert [e["i"] for e in calls] == [1, 2, 3, 4]  # and the ledger is in call order
    assert {e["i"]: e["cmd"] for e in calls} == {1: "slow", 2: "ls a", 3: "ls b", 4: "ls c"}


def test_a_failing_run_after_a_parallel_batch_is_still_the_latest_run(tmp_path, monkeypatch):
    """Before the fix the batch's edit and the later failing run both became "call 2", so the run did not count as
    after the edit and "All tests pass." went out with no 🧢."""
    eng = make(tmp_path)

    def edit():
        eng.on_tool(tool_name="patch", args={"path": "src/app.py", "old_string": "a", "new_string": "b"},
                    result=json.dumps({"success": True}), session_id="s", turn_id="t", status="ok")

    batch_with_a_slow_call(eng, monkeypatch, [lambda: term(eng, "ls a", "a"), edit])
    term(eng, "pytest -q", PY_FAIL, 1)
    out = eng.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m", platform="cli")
    r = [x for x in eng.store.last("s")["receipts"] if x["kind"] == "tests"][0]
    assert (r["verdict"], r["cite"], r["cmd"]) == ("CAP", 4, "pytest -q")
    assert "🧢" in out and "call 4" in out


def test_many_threads_reporting_at_once(tmp_path):
    eng = make(tmp_path)
    gate = threading.Barrier(16)

    def call(n):
        gate.wait(10)
        term(eng, f"ls d{n}", "x")

    threads = [threading.Thread(target=call, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert [e["i"] for e in eng._peek("s")] == list(range(1, 17))


def test_numbers_restart_with_the_next_turn_and_evicted_turns_are_forgotten(tmp_path):
    eng = make(tmp_path)
    term(eng, "ls a", "a")
    term(eng, "ls b", "b")
    eng.on_reply(response_text="Listed both.", session_id="s", turn_id="t", model="m", platform="cli")
    term(eng, "ls c", "c")
    assert [e["i"] for e in eng._peek("s")] == [1]
    for n in range(engine_mod.MAX_OPEN_TURNS + 5):  # open turns that never get a reply are evicted, counters too
        eng.on_tool(tool_name="terminal", args={"command": "ls"}, result="x", session_id=f"s{n}", turn_id="t")
    assert len(eng._turns) == engine_mod.MAX_OPEN_TURNS
    assert set(eng._seq) <= set(eng._turns)


def test_the_newest_calls_are_kept_past_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "MAX_CALLS", 5)
    eng = make(tmp_path)
    for n in range(8):
        term(eng, f"ls d{n}", "x")
    assert [e["i"] for e in eng._peek("s")] == [4, 5, 6, 7, 8]
