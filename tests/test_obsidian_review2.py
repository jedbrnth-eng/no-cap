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


# ---- R3: pre_llm_call reads a small cache, never the whole store ------------------------------------------------
import json  # noqa: E402
import random  # noqa: E402
import stat as _stat  # noqa: E402

from nocap.coach import BY_ID  # noqa: E402

REC = {"type": "reply", "profile": "alpha", "model": "m", "ts": 1.0, "receipts": [R]}


def _store_of(tmp_path, size, rec=REC):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    line = (json.dumps(rec) + "\n").encode()
    n = size // len(line)
    (d / "receipts.jsonl").write_bytes(line * n + b" " * (size - n * len(line)))
    return d / "receipts.jsonl"


def _turn_cpu_ms(e):
    t0 = time.process_time()
    got = e.on_turn_start(session_id="s", model="m")
    return (time.process_time() - t0) * 1000, got


def test_r3_enabled_turn_start_cpu_is_bounded_on_a_50MB_store(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, cfg_for(v))
    _store_of(tmp_path, 50_000_000)
    for i in range(3):
        cpu, got = _turn_cpu_ms(e)
        assert cpu <= 50, f"turn {i}: pre_llm_call CPU {cpu:.1f} ms on a 50 MB store"
        assert got and BY_ID["tests.failed_run"]["rule"] in got["context"]


def test_r3_turn_start_never_reads_the_whole_store(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, cfg_for(v))
    _store_of(tmp_path, 300_000)
    e.store.records = lambda: (_ for _ in ()).throw(AssertionError("pre_llm_call parsed the whole store"))
    assert e.on_turn_start(session_id="s", model="m")  # first turn builds the cache (bounded)
    read = []
    real_open = open

    class Counting:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.fh.close()

        def __getattr__(self, k):
            return getattr(self.fh, k)

        def read(self, n=-1):
            b = self.fh.read(n)
            read.append(len(b))
            return b

    def spy(path, mode="r", *a, **kw):
        fh = real_open(path, mode, *a, **kw)
        return Counting(fh) if str(path).endswith("receipts.jsonl") else fh

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O, "open", spy, raising=False)
        for _ in range(3):
            assert e.on_turn_start(session_id="s", model="m")
    assert sum(read) <= 3 * 1024, f"read {sum(read)} store bytes over 3 turns with nothing appended"


def test_r3_appended_caps_are_counted_incrementally(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, cfg_for(v))
    assert e.on_turn_start(session_id="s", model="m") is None  # empty store, no lesson
    _cap_reply(e, "t1")
    assert e.on_turn_start(session_id="s", model="m") is None  # one cap is not yet a lesson
    _cap_reply(e, "t2")
    got = e.on_turn_start(session_id="s", model="m")
    assert got and "(tests.failed_run, 2× 🧢)" in got["context"]


def _random_records(seed, n=400):
    rnd = random.Random(seed)
    kinds = [("tests", ""), ("pushed", "no git push"), ("merged", "no merge"), ("committed", "no git commit"),
             ("deployed", ""), ("number", "")]
    out = []
    for i in range(n):
        rec = {"type": rnd.choice(["reply", "reply", "reply", "turn"]), "ts": float(i),
               "profile": rnd.choice(["alpha", "Alpha ", "bravo", "", None, "default"]), "model": rnd.choice("mn"),
               "receipts": []}
        for _ in range(rnd.randint(0, 3)):
            kind, why = rnd.choice(kinds)
            rec["receipts"].append({"kind": kind, "verdict": rnd.choice(["CAP", "NO_RECEIPT", "NO_CAP"]),
                                    "why": why, "claim": {"kind": kind, "fails": rnd.random() < 0.2}})
        out.append(rec)
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_r3_cached_lessons_equal_a_full_mine(tmp_path, seed):
    v = tmp_path / "vault"
    v.mkdir()
    recs = _random_records(seed)
    d = tmp_path / "data"
    d.mkdir()
    (d / "receipts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    for who in ("alpha", "bravo", "default"):
        b = bridge(tmp_path, cfg_for(v), agent=who)
        assert b.lessons_cached(d / "receipts.jsonl") == O.lesson_text(recs, who), who


def test_r3_cache_file_is_private_and_holds_no_claim_text(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, cfg_for(v))
    marker = "zebra-sentinel-claim-text"
    rec = dict(REC, receipts=[dict(R, text=marker, quote=marker, claim={"kind": "tests", "frag": marker})])
    _store_of(tmp_path, 20_000, rec)
    assert e.on_turn_start(session_id="s", model="m")
    cache = tmp_path / "data" / O.LESSONS_FILE
    assert _stat.S_IMODE(cache.stat().st_mode) == 0o600
    raw = cache.read_text(encoding="utf-8")
    assert marker not in raw
    got = json.loads(raw)
    assert set(got["counts"]) == {"alpha"} and set(got["counts"]["alpha"]) <= set(BY_ID)


def test_r3_purge_and_replace_rebuild_the_cache(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, cfg_for(v))
    _cap_reply(e, "t1")
    _cap_reply(e, "t2")
    assert e.on_turn_start(session_id="s", model="m")
    assert "Removed" in e.nocap("purge", platform="cli")
    assert e.on_turn_start(session_id="s", model="m") is None  # the caps went with the store
    _cap_reply(e, "t3")
    assert e.on_turn_start(session_id="s", model="m") is None  # one cap after the purge, not three
    # a store replaced in place (prune): rebuilt from the new file, not added onto the old counts
    store = tmp_path / "data" / "receipts.jsonl"
    keep = store.read_bytes()
    tmp = store.with_suffix(".x")
    tmp.write_bytes(keep + keep)
    os.replace(tmp, store)
    for _ in range(3):
        got = e.on_turn_start(session_id="s", model="m")
    assert got and "(tests.failed_run, 2× 🧢)" in got["context"]


@pytest.mark.parametrize("cfg", [{"obsidian_vault": ""}, {"obsidian_learn": False}])
def test_r3_off_creates_no_cache_and_reads_no_store(tmp_path, cfg):
    v = tmp_path / "vault"
    v.mkdir()
    e = make_engine(tmp_path, {**cfg_for(v), **cfg})
    _store_of(tmp_path, 5_000)
    real_open = open
    opened = []

    def spy(path, *a, **kw):
        opened.append(str(path))
        return real_open(path, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O, "open", spy, raising=False)
        assert e.on_turn_start(session_id="s", model="m") is None
    assert opened == [] and not (tmp_path / "data" / O.LESSONS_FILE).exists()


# ---- R4: board work per cap write is bounded, not a walk over every board note ----------------------------------
R2CAP = {"kind": "pushed", "verdict": "CAP", "text": "I pushed it.", "why": "no git push", "claim": {"kind": "pushed"}}


def _big_board(v, n):
    board = v / "Agent Black Box" / "Mistakes"
    (board / ".ids").mkdir(parents=True)
    for i in range(1, n + 1):  # ABB's own layout: M-NNNN <slug>.md plus the reservation .ids/NNNN
        (board / f"M-{i:04d} Unrelated mistake.md").touch()
        (board / ".ids" / f"{i:04d}").touch()
    return board


def _count_names(fn):
    real = os.scandir
    seen = []

    def scan(*a, **kw):
        with real(*a, **kw) as it:
            for x in it:
                seen.append(x.name)
                yield x

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O.os, "scandir", scan)
        got = fn()
    return got, len(seen)


@pytest.mark.parametrize("n", [5000, 20000])
def test_r4_big_board_first_write_lists_no_names(tmp_path, n):
    v = tmp_path / "vault"
    _big_board(v, n)
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    got, names = _count_names(lambda: b.record([R], "s", "t"))
    assert got["written"] == 1 and got["board"] and got["board"][0].startswith(f"M-{n + 1:04d} ")
    assert names <= 100, f"listed {names} names for one cap write"


def test_r4_steady_state_lists_nothing_and_still_dedupes(tmp_path):
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    assert len(b.record([R], "s", "t1")["board"]) == 1  # first use of a small board: one bounded listing
    got, names = _count_names(lambda: b.record([R2CAP], "s", "t2"))
    assert len(got["board"]) == 1 and got["board"][0].startswith("M-0002 ") and names == 0
    again = bridge(tmp_path, cfg_for(v, obsidian_board="on"))  # a new process, same data dir
    got, names = _count_names(lambda: again.record([R, R2CAP], "s", "t3"))
    assert got["board"] == [] and names == 0
    assert len(list((v / "Agent Black Box" / "Mistakes").glob("M-*.md"))) == 2


def test_r4_stale_hint_probes_forward_boundedly(tmp_path):
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    b.record([R], "s", "t1")
    ids = v / "Agent Black Box" / "Mistakes" / ".ids"
    for i in range(2, 3001):  # another writer (ABB, another Hermes home) took ids 2..3000 meanwhile
        (ids / f"{i:04d}").touch()
    probes = []
    real_stat = os.stat

    def spy(path, *a, **kw):
        probes.append(str(path))
        return real_stat(path, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(O.os, "stat", spy)
        got, names = _count_names(lambda: b.record([R2CAP], "s", "t2"))
    assert got["board"][0].startswith("M-3001 ") and names == 0
    assert len(probes) <= 64, f"{len(probes)} stat probes"


def test_r4_deleted_board_note_is_written_again(tmp_path):
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    (first,) = b.record([R], "s", "t1")["board"]
    (v / "Agent Black Box" / "Mistakes" / first).unlink()
    (second,) = b.record([R], "s", "t2")["board"]
    assert second.startswith("M-0002 ")


def test_r4_board_index_is_private_and_holds_no_claim_text(tmp_path):
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    marker = "zebra-sentinel-board-claim"
    b = bridge(tmp_path, cfg_for(v, obsidian_board="on"))
    b.record([dict(R, text=marker, quote=marker)], "s", "t1")
    (idx,) = list((tmp_path / "data").glob("obsidian-board-*.json"))
    assert _stat.S_IMODE(idx.stat().st_mode) == 0o600
    raw = idx.read_text(encoding="utf-8")
    assert marker not in raw
    got = json.loads(raw)
    assert set(got["keys"]) == {"alpha:tests.failed_run"} and got["next"] == 2
