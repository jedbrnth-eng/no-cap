"""Second cross-family review of the Obsidian lessons bridge (Sol, PR #29 at 7e27de5, findings R1-R4): each finding as
tests, plus the probes' acceptance cases.

Everything runs on made-up vaults under tmp_path; no real vault, no real Hermes home, synthetic values only.
"""
import os
import signal
import time
from pathlib import Path

import pytest

from nocap import obsidian as O
from nocap.engine import Engine

R = {"kind": "tests", "verdict": "CAP", "text": "All tests pass.", "quote": "3 failed",
     "claim": {"kind": "tests", "all_pass": True, "fails": False}}
POSIX = pytest.mark.skipif(O.fcntl is None or not hasattr(signal, "setitimer"), reason="POSIX flock and itimer")


def cfg_for(vault, **extra):
    return {"obsidian_vault": str(vault), "obsidian_board": "off", "obsidian_learn": True, "cross_turn": False,
            **extra}


def make_engine(tmp_path, cfg, agent="alpha"):
    e = Engine(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d))
    e.profile = lambda: agent
    return e


def bridge(tmp_path, cfg, agent="alpha"):
    return O.Bridge(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d), lambda: agent)


def entries(path):
    return sum(l.startswith("- ") for l in Path(path).read_text(encoding="utf-8").splitlines())


class _Watchdog(BaseException):
    pass


def _run_bounded(fn, budget=2.0):
    """Run fn under a SIGALRM watchdog; returns (result, wall seconds). A hang raises AssertionError, not a freeze."""
    def fire(sig, frame):
        raise _Watchdog()
    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, budget)
    t0 = time.monotonic()
    try:
        try:
            got = fn()
        except _Watchdog:
            raise AssertionError(f"blocked for the {budget}s watchdog budget")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
    return got, time.monotonic() - t0


class _Held:
    """An independent exclusive flock on a folder, as another Hermes home (or a stuck one) would hold it."""

    def __init__(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        O.fcntl.flock(self.fd, O.fcntl.LOCK_EX)

    def release(self):
        if self.fd is not None:
            O.fcntl.flock(self.fd, O.fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def _cap_reply(e, tid="t"):
    e.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result={"output": "3 failed, 41 passed",
              "exit_code": 1}, session_id="s", turn_id=tid)
    return e.on_reply(response_text="All tests pass.", session_id="s", turn_id=tid, platform="cli")


# ---- R1: a held destination lock must not freeze the reply -------------------------------------------------------
@POSIX
@pytest.mark.parametrize("board", [False, True])
def test_r1_held_lock_skips_the_export_and_the_reply_finishes(tmp_path, board):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v, obsidian_board="on" if board else "off")
    e = make_engine(tmp_path, cfg)
    held = _Held(v / ("Agent Black Box/Mistakes" if board else "No Cap"))
    try:
        out, wall = _run_bounded(lambda: _cap_reply(e))
    finally:
        held.release()
    assert "🧢" in out
    assert wall < 0.25, f"reply took {wall:.3f}s with the lock held"
    assert "busy" in e.obsidian.last_error
    if board:
        assert entries(v / "No Cap" / "alpha.md") == 1  # the note folder was free: its line landed
        assert not list((v / "Agent Black Box" / "Mistakes").glob("M-*.md"))
    else:
        assert not (v / "No Cap" / "alpha.md").exists()


@POSIX
@pytest.mark.parametrize("board", [False, True])
def test_r1_skipped_export_is_picked_up_by_the_next_write(tmp_path, board):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v, obsidian_board="on" if board else "off")
    e = make_engine(tmp_path, cfg)
    held = _Held(v / ("Agent Black Box/Mistakes" if board else "No Cap"))
    try:
        _run_bounded(lambda: _cap_reply(e, "t1"))
    finally:
        held.release()
    _cap_reply(e, "t2")  # the next write, lock free: it also writes what the first turn skipped
    assert entries(v / "No Cap" / "alpha.md") == 2
    if board:
        assert len(list((v / "Agent Black Box" / "Mistakes").glob("M-*.md"))) == 1


@POSIX
def test_r1_skipped_export_is_picked_up_by_sync(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v)
    e = make_engine(tmp_path, cfg)
    held = _Held(v / "No Cap")
    try:
        _run_bounded(lambda: _cap_reply(e))
    finally:
        held.release()
    fresh = make_engine(tmp_path, cfg)  # a new process: the in-memory queue is gone, the store is not
    got = fresh.obsidian.sync(fresh.store.records())
    assert got["written"] == 1 and entries(v / "No Cap" / "alpha.md") == 1


@POSIX
def test_r1_lock_wait_is_bounded_per_call(tmp_path):
    """Both folders held: one record() call still returns well inside the 250 ms budget."""
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v, obsidian_board="on")
    b = bridge(tmp_path, cfg)
    b.record([R], "s", "t0")  # create both folders
    a = _Held(v / "No Cap")
    c = _Held(v / "Agent Black Box" / "Mistakes")
    try:
        got, wall = _run_bounded(lambda: b.record([R], "s", "t1"))
    finally:
        a.release()
        c.release()
    assert got["written"] == 0 and "busy" in got["skipped"]
    assert wall < 0.25
