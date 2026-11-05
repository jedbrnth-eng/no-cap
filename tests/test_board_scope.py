"""Cap Board scope (security review 3-A, 3-B, 3-C).

3-A: by default the board shows ONLY the profile it is asked from. The multi-profile team view is an explicit opt-in
     (``plugins.entries.no-cap.settings.board.team_profiles``: a list of profile names, or ``all``), and even then a
     ``/capscore board`` from a gateway chat (telegram, discord, ...) shows only the current profile: team mode is
     served on ``cli`` and the dashboard only.
3-B: a folder entry in ``board_sources`` is walked with a depth and a count bound, decided before walking, and never
     through a symlinked directory.
3-C: the demo backfill runs argv lists with a timeout, never ``shell=True``.
"""
import ast
import json
from pathlib import Path

import pytest

from test_board import Agent, _api, board_mod, make_root

ROOT = Path(__file__).resolve().parents[1]


def three_profiles(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alice", "bob"))
    Agent(root, "default", monkeypatch).lie()
    Agent(root, "alice", monkeypatch).turn("All tests pass for alice's client.",
                                           [("pytest -q", "3 failed, 41 passed (private repo /srv/alice-acme)", 1)])
    bob = Agent(root, "bob", monkeypatch)
    bob.honest()
    return root, bob


def agents_of(b):
    return sorted(r["name"] for r in b["agents"]), sorted({h["agent"] for h in b["hall"]})


# ---- the scope decision ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("spec,want", [
    (None, None), ("", None), ([], None), ("off", None), ("none", None), (False, None),
    ("all", "all"), ("ALL", "all"), (["all"], "all"), ("*", "all"),
    (["alice", "bob"], ["alice", "bob"]), ("alice, bob", ["alice", "bob"]), ("alice bob", ["alice", "bob"]),
    (["Bad Name", "ok"], ["ok"]), (42, None),
])
def test_team_setting_parses_strictly(spec, want):
    assert board_mod().parse_team(spec) == want


def test_default_scope_is_the_current_profile_only(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    B = board_mod()
    B.clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    srcs, scope = B.scoped_sources(team=None, platform="dashboard", root=root)
    assert [s.label for s in srcs] == ["bob"]
    assert scope == {"mode": "profile", "profile": "bob", "team_setting": False, "profiles": ["bob"]}
    b = B.build_board(srcs)
    assert agents_of(b) == (["bob"], [])
    assert "alice" not in json.dumps(b)


def test_extra_sources_are_ignored_outside_team_mode(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    B = board_mod()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    alice_home = root / "profiles" / "alice"
    srcs, _ = B.scoped_sources(team=None, platform="cli", root=root, extra=B.parse_sources(f"a={alice_home}"))
    assert [s.label for s in srcs] == ["bob"]
    srcs, _ = B.scoped_sources(team="all", platform="cli", root=root, extra=B.parse_sources(f"a={alice_home}"))
    assert "bob" in [s.label for s in srcs]


@pytest.mark.parametrize("platform", ["cli", "dashboard"])
def test_team_all_is_served_on_cli_and_dashboard(tmp_path, monkeypatch, platform):
    root, bob = three_profiles(tmp_path, monkeypatch)
    B = board_mod()
    B.clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    srcs, scope = B.scoped_sources(team="all", platform=platform, root=root)
    assert [s.label for s in srcs] == ["default", "alice", "bob"]
    assert scope["mode"] == "team" and scope["team_setting"] is True


@pytest.mark.parametrize("platform", ["telegram", "discord", "slack", "whatsapp", "tui", "desktop", "", "CLI "])
def test_team_mode_never_reaches_gateway_chats(tmp_path, monkeypatch, platform):
    root, bob = three_profiles(tmp_path, monkeypatch)
    B = board_mod()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    srcs, scope = B.scoped_sources(team="all", platform=platform, root=root)
    if platform.strip().lower() == "cli":
        assert scope["mode"] == "team"
        return
    assert [s.label for s in srcs] == ["bob"]
    assert scope == {"mode": "profile", "profile": "bob", "team_setting": True, "profiles": ["bob"]}


def test_team_list_shows_only_the_named_profiles_plus_the_current_one(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    B = board_mod()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    srcs, scope = B.scoped_sources(team=["alice"], platform="cli", root=root)
    assert [s.label for s in srcs] == ["alice", "bob"]
    assert scope["profiles"] == ["alice", "bob"]


# ---- /capscore board -----------------------------------------------------------------------------------------------
def test_capscore_board_shows_only_this_profile_by_default(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    board_mod().clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    out = bob.ctx.commands["capscore"]("board", session_id="", platform="cli")
    assert "alice" not in out and "/srv/alice-acme" not in out
    assert "bob" in out and "this profile only" in out


@pytest.mark.parametrize("platform", ["telegram", "discord"])
def test_capscore_board_in_a_gateway_chat_is_this_profile_even_in_team_mode(tmp_path, monkeypatch, platform):
    root, bob = three_profiles(tmp_path, monkeypatch)
    bob.ctx.settings["board.team_profiles"] = "all"
    board_mod().clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    out = bob.ctx.commands["capscore"]("board", session_id="", platform=platform)
    assert "alice" not in out and "/srv/alice-acme" not in out
    assert "team view is only shown in the CLI and the dashboard" in out


def test_capscore_board_team_mode_on_cli(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    bob.ctx.settings["board.team_profiles"] = "all"
    board_mod().clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    out = bob.ctx.commands["capscore"]("board", session_id="", platform="cli")
    assert "alice" in out and "team view" in out


def test_capscore_board_without_a_platform_fails_closed(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    bob.ctx.settings["board.team_profiles"] = "all"
    board_mod().clear_cache()
    monkeypatch.setenv("HERMES_HOME", str(bob.home))
    out = bob.ctx.commands["capscore"]("board", session_id="")  # a host that doesn't pass platform
    assert "alice" not in out


# ---- dashboard route ------------------------------------------------------------------------------------------------
def test_dashboard_board_as_bob_never_shows_alice(tmp_path, monkeypatch):
    """The exploit (sec/exploits/pr3_board.py) as a test: the route scoped to bob's profile."""
    root, bob = three_profiles(tmp_path, monkeypatch)
    client = _api(monkeypatch, bob.home)
    b = client.get("/api/plugins/no-cap/board").json()
    assert [s["label"] for s in b["sources"]] == ["bob"]
    assert agents_of(b) == (["bob"], [])
    assert "alice" not in json.dumps(b) and b["scope"]["mode"] == "profile"


def test_dashboard_team_mode_is_opt_in_from_config(tmp_path, monkeypatch):
    root, bob = three_profiles(tmp_path, monkeypatch)
    client = _api(monkeypatch, bob.home)
    monkeypatch.setattr(client.api_module, "_settings", lambda: {"board": {"team_profiles": "all"}})
    b = client.get("/api/plugins/no-cap/board").json()
    assert [s["label"] for s in b["sources"]] == ["default", "alice", "bob"]
    assert b["scope"]["mode"] == "team"


# ---- 3-B: bounded folder walk ---------------------------------------------------------------------------------------
def test_folder_walk_is_depth_bounded(tmp_path, monkeypatch):
    B = board_mod()
    deep = tmp_path / "tree"
    d = deep
    for i in range(B.MAX_WALK_DEPTH + 3):
        d = d / f"d{i}"
    d.mkdir(parents=True)
    (d / "receipts.jsonl").write_text("{}\n")
    shallow = deep / "d0" / "receipts.jsonl"
    shallow.write_text("{}\n")
    found = B._paths_of(str(deep))
    assert shallow in found and (d / "receipts.jsonl") not in found


def test_folder_walk_stops_at_the_directory_budget(tmp_path, monkeypatch):
    B = board_mod()
    monkeypatch.setattr(B, "MAX_WALK_DIRS", 20)
    top = tmp_path / "wide"
    for i in range(200):
        (top / f"x{i:03d}").mkdir(parents=True)
    visited = []
    real = B.os.scandir

    def counting(p):
        visited.append(p)
        return real(p)

    monkeypatch.setattr(B.os, "scandir", counting)
    B._paths_of(str(top))
    assert len(visited) <= 20


def test_folder_walk_never_follows_symlinked_dirs(tmp_path):
    B = board_mod()
    top = tmp_path / "t"
    (top / "real").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "receipts.jsonl").write_text("{}\n")
    (top / "link").symlink_to(outside, target_is_directory=True)
    (top / "loop").symlink_to(top, target_is_directory=True)
    assert B._paths_of(str(top)) == []


def test_folder_walk_caps_the_file_count(tmp_path, monkeypatch):
    B = board_mod()
    monkeypatch.setattr(B, "MAX_GLOB_FILES", 3)
    top = tmp_path / "many"
    for i in range(10):
        (top / f"r{i}").mkdir(parents=True)
        (top / f"r{i}" / "receipts.jsonl").write_text("{}\n")
    assert len(B._paths_of(str(top))) == 3


# ---- 3-C: demo backfill -----------------------------------------------------------------------------------------------
def test_demo_backfill_runs_argv_lists_with_a_timeout():
    tree = ast.parse((ROOT / "demo" / "board_backfill.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("run", "Popen", "call", "check_call", "check_output")
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    assert calls
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert "timeout" in kw, "subprocess call without a timeout"
        shell = kw.get("shell")
        assert shell is None or (isinstance(shell, ast.Constant) and shell.value is False), "shell=True"
