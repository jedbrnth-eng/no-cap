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


# ---- R2: a pinned folder moved out of the vault (path replaced by a symlink) gets no new write -------------------
def _swap_out(src, outside, name):
    """Move src to outside/name and leave a symlink to `outside` where it was."""
    outside.mkdir(exist_ok=True)
    src.rename(outside / name)
    src.symlink_to(outside, target_is_directory=True)


def _files(d):
    return sorted(str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file() or p.is_symlink())


@pytest.mark.parametrize("what", ["folder", "vault"])
def test_r2_note_folder_or_vault_moved_after_pinning_gets_no_line(tmp_path, what):
    v = tmp_path / "vault"
    v.mkdir()
    b = bridge(tmp_path, cfg_for(v))
    assert b.record([R], "s", "old")["written"] == 1
    outside = tmp_path / "outside"
    original = O._replace

    def move(path, data, mode, **kw):
        _swap_out(v / "No Cap" if what == "folder" else v, outside, "moved")
        return original(path, data, mode, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O, "_replace", move)
        got = b.record([R], "s", "new")
    moved_note = outside / "moved" / ("alpha.md" if what == "folder" else "No Cap/alpha.md")
    assert entries(moved_note) == 1, "a new line went to the folder moved outside the vault"
    assert got["written"] == 0 and "moved" in got["skipped"]
    assert not [f for f in _files(outside) if "nocap-tmp" in f]  # no temp file left behind either


@pytest.mark.parametrize("what", ["board", "ids"])
def test_r2_board_or_ids_folder_moved_after_pinning_gets_no_file(tmp_path, what):
    v = tmp_path / "vault"
    board = v / "Agent Black Box" / "Mistakes"
    (board / ".ids").mkdir(parents=True)
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    outside = tmp_path / "outside"
    original = O._write_new
    moved = []

    def move(path, data, dir_fd=None, **kw):
        if not moved:
            moved.append(1)
            _swap_out(board if what == "board" else board / ".ids", outside, "moved")
        return original(path, data, dir_fd=dir_fd, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O, "_write_new", move)
        got = b.record([R], "s", "t")
    assert _files(outside) == [], f"board write landed outside the vault: {_files(outside)}"
    assert got["board"] == [] and "moved" in b.last_error
    assert entries(v / "No Cap" / "alpha.md") == 1  # the note folder did not move: its line landed


def test_r2_an_unmoved_destination_still_writes(tmp_path):
    """Control: the re-check passes when nothing moved (a configured symlinked vault path included)."""
    real = tmp_path / "real"
    (real / "Agent Black Box").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    b = bridge(tmp_path, cfg_for(link, obsidian_board="on"))
    got = b.record([R], "s", "t")
    assert got["written"] == 1 and len(got["board"]) == 1
