"""Cross-family review of the Obsidian lessons bridge (Sol, PR #24 at a5dae95, findings B1-B7): each probe as a test.

Everything runs on made-up vaults under tmp_path; no real vault, no real Hermes home, synthetic secrets only.
"""
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from nocap import obsidian as O
from nocap.engine import Engine
from nocap.evidence import redact

R = {"kind": "tests", "verdict": "CAP", "text": "All tests pass.", "quote": "3 failed", "claim": {"kind": "tests"}}


def cfg_for(vault, **extra):
    return {"obsidian_vault": str(vault), "obsidian_board": "off", "obsidian_learn": True, **extra}


def bridge(data, cfg, agent="alpha"):
    return O.Bridge(lambda: data, lambda k, d=None: cfg.get(k, d), lambda: agent)


def entries(path):
    return sum(l.startswith("- ") for l in Path(path).read_text(encoding="utf-8").splitlines())


# ---- B1: a vault ancestor swapped for a symlink between resolve and open -----------------------------------------
def test_b1_ancestor_swap_does_not_write_outside(tmp_path):
    parent = tmp_path / "parent"
    (parent / "vault").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "vault").mkdir(parents=True)
    cfg = cfg_for(parent / "vault")
    b = bridge(tmp_path / "data", cfg)
    orig = b.vault

    def race():
        root = orig()
        parent.rename(tmp_path / "kept")
        parent.symlink_to(outside, target_is_directory=True)
        return root

    b.vault = race
    got = b.record([R], "s", "t")
    assert not (outside / "vault" / "No Cap" / "alpha.md").exists()
    assert got["written"] == 0 and got["skipped"]
    assert not (tmp_path / "kept" / "vault" / "No Cap" / "alpha.md").exists()  # refused, not silently redirected


def test_b1_static_symlinked_vault_path_is_allowed(tmp_path):
    """Documented choice: a symlink the user put in the configured vault path is resolved once per write and used."""
    real = tmp_path / "real-vault"
    real.mkdir()
    link = tmp_path / "link-vault"
    link.symlink_to(real, target_is_directory=True)
    b = bridge(tmp_path / "data", cfg_for(link))
    assert b.record([R], "s", "t")["written"] == 1
    assert (real / "No Cap" / "alpha.md").is_file()


# ---- B2: unknown identity is never attributed to "default" -------------------------------------------------------
@pytest.mark.parametrize("unknown", ["", None, "   "])
def test_b2_unknown_profile_gets_no_lessons(tmp_path, unknown):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v)
    e = Engine(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d))
    e.profile = lambda: unknown
    e.store.records = lambda: [{"type": "reply", "profile": "default", "ts": i, "model": "m", "receipts": [R]}
                               for i in range(2)]
    assert e.on_turn_start(session_id="s", model="m") is None


@pytest.mark.parametrize("unknown", ["", None])
def test_b2_unknown_profile_writes_no_note(tmp_path, unknown):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v)
    e = Engine(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d))
    e.profile = lambda: unknown
    e.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result={"output": "1 failed, 2 passed in 0.1s",
              "exit_code": 1}, session_id="s", turn_id="t")
    out = e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m", platform="cli")
    assert "🧢" in out  # the verdict still shows; only the attribution is refused
    assert list(v.rglob("*.md")) == []


def test_b2_default_profile_still_works_when_named(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    assert bridge(tmp_path / "data", cfg_for(v), agent="default").record([R], "s", "t")["written"] == 1


# ---- B3: two Hermes homes (separate stores) on one vault must not lose an append ---------------------------------
def test_b3_separate_stores_preserve_both_appends(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v)
    bridge(tmp_path / "data0", cfg).record([R], "s", "t0")
    # Both writers try to read the note at the same moment. Without a per-note lock both read the same old bytes
    # and the second replace drops the first append. With the lock the second blocks, the barrier times out
    # (tolerated) and it reads the first writer's result.
    barrier = threading.Barrier(2)
    original = O._read_nofollow
    errors = []

    def read(path, limit, **kw):
        old = original(path, limit, **kw)
        if str(path) == "alpha.md":
            try:
                barrier.wait(timeout=1.5)
            except threading.BrokenBarrierError:
                pass
        return old

    def run(i):
        try:
            got = bridge(tmp_path / f"data{i + 1}", cfg).record([R], "s", f"t{i + 1}")
            if got["written"] != 1:
                errors.append(got)
        except Exception as ex:  # pragma: no cover - reported by the assert
            errors.append(repr(ex))

    with patch.object(O, "_read_nofollow", read):
        ts = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(15)
    assert errors == []
    assert entries(v / "No Cap" / "alpha.md") == 3


def test_b3_lock_lives_with_the_destination_not_the_store(tmp_path):
    """The lock is on the pinned note folder; No Cap's data dir gets no lock file and the vault no extra file."""
    v = tmp_path / "vault"
    v.mkdir()
    bridge(tmp_path / "data", cfg_for(v)).record([R], "s", "t")
    assert not (tmp_path / "data" / "obsidian.lock").exists()
    assert sorted(p.name for p in (v / "No Cap").iterdir()) == ["alpha.md"]


# ---- B4: feature off reads nothing -------------------------------------------------------------------------------
@pytest.mark.parametrize("cfg", [{"obsidian_vault": ""}, {"obsidian_vault": "/tmp/x", "obsidian_learn": False}])
def test_b4_off_does_not_read_store(tmp_path, cfg):
    e = Engine(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d))
    with patch.object(e.store, "records", return_value=[]) as reads:
        e.on_turn_start(session_id="s", model="m")
    assert reads.call_count == 0


# ---- B5: a secret clipped upstream must not reach the vault (fixed upstream in nocap/evidence.py, PR #27) --------
def test_b5_full_tool_field_is_redacted_before_vault_export(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v, obsidian_board="on")
    e = Engine(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d))
    e.profile = lambda: "alpha"
    password = "syntheticordinary-" * 20  # synthetic, not a credential
    raw = "3 failed, 41 passed in 0.02s postgres://demo:" + password + "@example.invalid/db"
    assert password not in redact(raw)
    e.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result={"output": raw, "exit_code": 1},
              session_id="s", turn_id="t")
    e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", platform="cli")
    written = list(v.rglob("*.md"))
    assert written  # the 🧢 was exported, so the check below is not vacuous
    for n in written:
        assert "syntheticordinary-" not in n.read_text(encoding="utf-8"), str(n)


# ---- B6: a cap turn's board work is bounded, not a scan of every board note -------------------------------------
def test_b6_board_write_does_not_open_unrelated_notes(tmp_path):
    v = tmp_path / "vault"
    board = v / "Agent Black Box" / "Mistakes"
    board.mkdir(parents=True)
    (v / ".agentbox.json").write_text("{}", encoding="utf-8")
    for i in range(150):
        (board / f"M-{i + 1:04d} Some other mistake {i}.md").write_text("---\nid: x\n---\n", encoding="utf-8")
    b = bridge(tmp_path / "data", cfg_for(v, obsidian_board="on"))
    opened = []
    real_open = os.open

    def spy(path, *a, **kw):
        if str(path).endswith(".md"):
            opened.append(str(path))
        return real_open(path, *a, **kw)

    with patch.object(O.os, "open", spy):
        got = b.record([R], "s", "t")
    assert got["written"] == 1 and len(got["board"]) == 1
    assert len(opened) <= 4, opened  # the agent note (+ temp), the new board note; not the 150 others
    assert got["board"][0].startswith("M-0151 ")


def test_b6_board_duplicate_is_still_suppressed(tmp_path):
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    b = bridge(tmp_path / "data", cfg_for(v, obsidian_board="on"))
    assert len(b.record([R], "s", "t1")["board"]) == 1
    assert b.record([R], "s", "t2")["board"] == []


# ---- B7: identities stay strings in YAML -------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["123", "null", "true", "1e3", "0x1f"])
def test_b7_yaml_profile_is_still_a_string(name):
    yaml = pytest.importorskip("yaml")
    head = O.note_header(name).decode().split("---")[1]
    assert yaml.safe_load(head)["agent"] == name
    _, text = O.board_note(1, name, "tests.failed_run", "2026-11-10", "c", "e", "No Cap/" + name)
    assert yaml.safe_load(text.split("---")[1])["agent"] == name


# ---- break-it: the fixes under harder versions of the same attacks ---------------------------------------------
def _own_store_append(vault, data, i):
    cfg = {"obsidian_vault": str(vault), "obsidian_board": "on"}
    got = O.Bridge(lambda: Path(data), lambda k, d=None: cfg.get(k, d), lambda: "alpha").record([R], "p", f"t{i}")
    assert got["written"] == 1, got


def test_break_it_eight_processes_eight_stores_one_vault(tmp_path):
    """B3 for real: eight processes, each with its OWN data dir (eight Hermes homes), append to one note."""
    import multiprocessing
    v = tmp_path / "vault"
    (v / "Agent Black Box").mkdir(parents=True)
    ctx = multiprocessing.get_context("spawn")
    kids = [ctx.Process(target=_own_store_append, args=(v, tmp_path / f"data{i}", i)) for i in range(8)]
    for k in kids:
        k.start()
    try:
        for k in kids:
            k.join(timeout=30)
            assert k.exitcode == 0
    finally:
        for k in kids:
            if k.is_alive():
                k.terminate()
                k.join(timeout=5)
    lines = [l for l in (v / "No Cap" / "alpha.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    assert len(lines) == len(set(lines)) == 8
    assert len(list((v / "Agent Black Box" / "Mistakes").glob("M-*.md"))) == 1  # board dedupe holds across stores


def test_break_it_grandparent_swap_and_swap_back_to_same_tree(tmp_path):
    """B1: swap a GRANDparent, and separately swap an ancestor for a symlink to the very same tree. Both refused:
    once resolved, the vault path must be walked without any symlink, whatever the link points at."""
    gp = tmp_path / "gp"
    (gp / "parent" / "vault").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "parent" / "vault").mkdir(parents=True)
    b = bridge(tmp_path / "data", cfg_for(gp / "parent" / "vault"))
    orig = b.vault

    def race_gp():
        root = orig()
        gp.rename(tmp_path / "kept")
        gp.symlink_to(outside, target_is_directory=True)
        return root

    b.vault = race_gp
    assert b.record([R], "s", "t")["written"] == 0
    assert list(outside.rglob("*.md")) == []
    gp.unlink()
    (tmp_path / "kept").rename(gp)
    b.vault = orig
    assert b.record([R], "s", "t")["written"] == 1  # untouched path: writes again

    def race_same():
        root = orig()
        (tmp_path / "kept2").symlink_to(gp / "parent", target_is_directory=True)
        (gp / "parent").rename(tmp_path / "real-parent")
        (tmp_path / "kept2").rename(gp / "parent")
        return root

    b.vault = race_same
    assert b.record([R], "s", "t2")["written"] == 0
