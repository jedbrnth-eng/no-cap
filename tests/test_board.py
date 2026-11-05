"""Cap Board: aggregation per agent (Hermes profile), model and skill across every profile's store, read-only.

Records come from the real hook pipeline (register() → post_tool_call → transform_llm_output) wherever the
test is about what the plugin writes; only the corrupt-line and 10k-record tests write JSONL directly.
"""
import json
import os
import stat
import time
from pathlib import Path

import pytest

from test_plugin import FakeCtx, load_plugin

DAY = 86400.0


@pytest.fixture(autouse=True)
def _no_profile_pin(monkeypatch):
    for k in ("HERMES_PROFILE_NAME", "HERMES_PROFILE", "NOCAP_BOARD_SOURCES"):
        monkeypatch.delenv(k, raising=False)

def board_mod():
    load_plugin()
    import sys
    return sys.modules["nocap_plugin_under_test.nocap.board"]


# ---- helpers: a throwaway Hermes root with profiles, each writing through the real plugin ---------------
def make_root(tmp_path, names=("alpha",)):
    root = tmp_path / "hroot"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text("model: {}\n")
    for n in names:
        if n == "default":
            continue
        d = root / "profiles" / n
        d.mkdir(parents=True)
        (d / "config.yaml").write_text("model: {}\n")
    return root


def home_of(root, name):
    return root if name == "default" else root / "profiles" / name


class Agent:
    """One profile's plugin instance, writing to <home>/plugin-data/<namespace> like Hermes would."""

    def __init__(self, root, name, monkeypatch, namespace="agent-plugin-no-cap-4890e304"):
        self.home = home_of(root, name)
        self.monkeypatch = monkeypatch
        self.mod = load_plugin()
        self.ctx = FakeCtx(self.home)
        self.ctx.state.data_dir = self.home / "plugin-data" / namespace
        self.monkeypatch.setenv("HERMES_HOME", str(self.home))
        self.mod.register(self.ctx)
        self.n = 0

    def turn(self, reply, tools=(), model="m-1", skills=()):
        self.monkeypatch.setenv("HERMES_HOME", str(self.home))
        self.n += 1
        sid, tid = f"s-{self.home.name}", f"t{self.n}"
        for s in skills:
            self.ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": s},
                                            result='{"success": true}', session_id=sid, turn_id=tid)
        for cmd, out, code in tools:
            self.ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": cmd},
                                            result=json.dumps({"output": out, "exit_code": code}),
                                            session_id=sid, turn_id=tid)
        return self.ctx.hooks["transform_llm_output"](response_text=reply, session_id=sid, turn_id=tid,
                                                      model=model, platform="cli")

    def lie(self, **kw):  # 🧢: says tests pass, pytest said 3 failed
        return self.turn("All tests pass.", [("pytest -q", "3 failed, 41 passed in 0.2s", 1)], **kw)

    def honest(self, **kw):  # 🧾: says tests pass, pytest agreed
        return self.turn("All tests pass.", [("pytest -q", "44 passed in 0.2s", 0)], **kw)

    @property
    def store(self):
        return self.ctx.state.data_dir / "receipts.jsonl"


def board_for(root, **kw):
    B = board_mod()
    B.clear_cache()
    return B.build_board(B.discover_sources(root=root), **kw)


def row(rows, name):
    return next(r for r in rows if r["name"] == name)


# ---- empty -----------------------------------------------------------------------------------------------
def test_empty_root_has_no_rows_and_a_friendly_text(tmp_path):
    root = make_root(tmp_path, ())
    b = board_for(root)
    assert b["agents"] == b["models"] == b["skills"] == b["hall"] == []
    assert b["totals"]["replies"] == 0 and b["totals"]["claims"] == 0
    assert "no checked replies" in board_mod().board_text(b).lower()


def test_missing_root_is_not_an_error(tmp_path):
    b = board_for(tmp_path / "nope")
    assert b["agents"] == []


# ---- one profile, through the real hooks ---------------------------------------------------------------------
def test_one_profile_records_profile_and_skills_at_hook_time(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.lie(skills=["github-pr-workflow"])
    rec = json.loads(a.store.read_text().splitlines()[-1])
    assert rec["profile"] == "alpha"
    assert rec["skills"] == ["github-pr-workflow"]
    b = board_for(root)
    assert [r["name"] for r in b["agents"]] == ["alpha"]
    r = b["agents"][0]
    assert (r["replies"], r["claims"], r["cap"], r["proven"]) == (1, 1, 1, 0)
    assert [s["name"] for s in b["skills"]] == ["github-pr-workflow"]
    assert b["models"][0]["name"] == "m-1"


def test_default_profile_is_named_default(tmp_path, monkeypatch):
    root = make_root(tmp_path, ())
    Agent(root, "default", monkeypatch).honest()
    b = board_for(root)
    assert [r["name"] for r in b["agents"]] == ["default"]


def test_profile_env_pin_wins_like_hermes(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "alpha"))
    monkeypatch.setenv("HERMES_PROFILE_NAME", "coder")
    assert board_mod().profile_name() == "coder"
    monkeypatch.delenv("HERMES_PROFILE_NAME")
    assert board_mod().profile_name() == "alpha"


def test_standalone_home_is_its_own_default_profile(tmp_path, monkeypatch):
    """Hermes treats a HERMES_HOME outside any profiles/ folder as a root, whose profile is 'default'.
    (Throwaway homes on one board get told apart with labelled sources instead.)"""
    home = tmp_path / "throwaway-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("HERMES_PROFILE_NAME", raising=False)
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    assert board_mod().profile_name() == "default"


def test_turn_without_skills_groups_under_no_skill(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    Agent(root, "alpha", monkeypatch).honest()
    b = board_for(root)
    assert [s["name"] for s in b["skills"]] == [board_mod().NO_SKILL]


# ---- min-sample rule ------------------------------------------------------------------------------------
def test_rates_hidden_below_min_sample(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    a, b_ = Agent(root, "alpha", monkeypatch), Agent(root, "beta", monkeypatch)
    for _ in range(3):
        a.lie()  # 3 claims, all caps: a 100% cap rate on n=3 must NOT rank
    for i in range(12):
        (b_.lie if i < 3 else b_.honest)()
    b = board_for(root)
    ra, rb = row(b["agents"], "alpha"), row(b["agents"], "beta")
    assert ra["cap_rate"] is None and ra["receipt_rate"] is None and ra["low_sample"] and ra["rank"] is None
    assert ra["claims"] == 3 and ra["cap"] == 3  # counts still shown, with the n
    assert rb["rank"] == 1 and rb["cap_rate"] == pytest.approx(3 / 12) and rb["receipt_rate"] == pytest.approx(9 / 12)
    assert [r["name"] for r in b["agents"]] == ["beta", "alpha"]  # ranked rows first
    text = board_mod().board_text(b)
    assert "n=3" in text and "100%" not in text


def test_min_claims_is_configurable(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    for _ in range(3):
        a.lie()
    b = board_for(root, min_claims=3)
    assert b["agents"][0]["cap_rate"] == 1.0 and b["agents"][0]["rank"] == 1


def test_ranking_is_top_cappers_first(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    a, b_ = Agent(root, "alpha", monkeypatch), Agent(root, "beta", monkeypatch)
    for i in range(10):
        (a.lie if i < 2 else a.honest)()
        (b_.lie if i < 6 else b_.honest)()
    b = board_for(root)
    assert [r["name"] for r in b["agents"]] == ["beta", "alpha"]
    assert [r["rank"] for r in b["agents"]] == [1, 2]


# ---- streak, top cap type, trend -------------------------------------------------------------------------
def test_streak_counts_replies_since_last_cap(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.honest(); a.lie(); a.honest(); a.honest(); a.honest()
    r = board_for(root)["agents"][0]
    assert r["streak"] == 3
    assert r["top_cap"] == "tests"


def _backdate(store: Path, days_ago_by_index):
    lines = store.read_text().splitlines()
    now = time.time()
    out = []
    for i, line in enumerate(lines):
        rec = json.loads(line)
        rec["ts"] = now - days_ago_by_index(i) * DAY
        out.append(json.dumps(rec))
    store.write_text("\n".join(out) + "\n")


def test_trend_compares_last_7_days_with_the_7_before(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    for i in range(20):  # previous week: 2/10 capped; this week: 6/10 capped → capping more → trend up
        if i < 10:
            (a.lie if i < 2 else a.honest)()
        else:
            (a.lie if i < 16 else a.honest)()
    _backdate(a.store, lambda i: 10 if i < 10 else 1)
    r = board_for(root)["agents"][0]
    t = r["trend"]
    assert t["prev"] == pytest.approx(0.2) and t["cur"] == pytest.approx(0.6)
    assert t["dir"] == "up" and t["delta"] == pytest.approx(0.4)


def test_trend_needs_min_sample_in_both_windows(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    for _ in range(12):
        a.lie()
    r = board_for(root)["agents"][0]  # all this week, nothing the week before
    assert r["trend"]["dir"] is None and r["trend"]["n_prev"] == 0 and r["trend"]["n_cur"] == 12


# ---- corrupt and hostile stores ------------------------------------------------------------------------
def test_corrupt_lines_are_skipped_and_counted(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.lie()
    with open(a.store, "ab") as fh:
        fh.write(b"not json\n[1,2,3]\n\xff\xfe\x00garbage\n{\"type\": \"reply\", \"receipts\": \"nope\"}\n")
        fh.write(b'{"type": "reply", "ts": "yesterday", "receipts": [{"verdict": "CAP"}, 7, null]}\n')
    a.lie()
    with open(a.store, "ab") as fh:
        fh.write(b'{"type": "reply", "ts": 1, "recei')  # a writer mid-append: no newline yet
    b = board_for(root)
    r = b["agents"][0]
    # the two real lies, the receipts:"nope" line (a reply with no usable claims) and the odd line with one CAP
    assert r["replies"] == 4 and r["cap"] == 3 and r["claims"] == 3
    src = b["sources"][0]
    assert src["bad_lines"] == 3 and src["records"] == 4  # not json, a list, the binary line; the partial waits
    assert "not json" not in json.dumps(b)


def test_fast_path_never_drops_verdicts_whatever_the_key_order(tmp_path):
    """The reader skips the ledger's calls without parsing them; a record in another key order, or with the marker
    text inside a string, must still be read in full."""
    cap = {"kind": "tests", "verdict": "CAP", "text": 'said "calls": [ and ], "ledger": in prose', "quote": "1 failed"}
    calls = [{"i": 1, "tool": "terminal", "cmd": 'echo "], \\"ledger\\": "'}]
    recs = [
        {"type": "reply", "ts": 1.0, "model": "m", "calls": calls, "ledger": {"n": 1}, "receipts": [cap]},
        {"type": "reply", "ts": 2.0, "model": "m", "calls": calls, "receipts": [cap], "ledger": {"n": 1}},
        {"receipts": [cap], "type": "reply", "ts": 3.0, "model": "m", "calls": calls, "ledger": {"n": 1}},
    ]
    p = tmp_path / "receipts.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))
    B = board_mod()
    B.clear_cache()
    b = B.build_board(B.discover_sources(root=tmp_path / "none", extra=B.parse_sources(f"x={p}")))
    assert b["totals"]["replies"] == 3 and b["totals"]["cap"] == 3 and b["sources"][0]["bad_lines"] == 0


def test_non_reply_records_are_not_scored(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.lie()
    a.ctx.commands["cap"]("", session_id="s-alpha")  # writes recheck/cap records
    b = board_for(root)
    assert b["agents"][0]["replies"] == 1


# ---- multi-profile discovery, read-only -----------------------------------------------------------------
def test_discovers_every_profile_the_way_hermes_does(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    (root / "profiles" / "ghost").mkdir()  # no identity marker: not a profile
    (root / "profiles" / "Bad Name").mkdir()
    (root / "profiles" / "Bad Name" / "config.yaml").write_text("{}")
    gone = root / "profiles" / "gone"
    gone.mkdir()
    (gone / "config.yaml").write_text("{}")
    (root / "profiles" / ".deleted").mkdir()
    (root / "profiles" / ".deleted" / "gone").write_text("")  # tombstone beside the profile dir
    Agent(root, "default", monkeypatch).honest()
    Agent(root, "alpha", monkeypatch).lie()
    Agent(root, "beta", monkeypatch, namespace="no-cap").honest()  # the older plugin_data_dir layout
    labels = [s.label for s in board_mod().discover_sources(root=root)]
    assert labels == ["default", "alpha", "beta"]
    b = board_for(root)
    assert sorted(r["name"] for r in b["agents"]) == ["alpha", "beta", "default"]


def test_stores_are_read_only(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    stores = []
    for n in ("alpha", "beta"):
        a = Agent(root, n, monkeypatch)
        a.lie()
        stores.append(a.store)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in stores}
    for p in stores:
        os.chmod(p, stat.S_IRUSR)
        os.chmod(p.parent, stat.S_IRUSR | stat.S_IXUSR)
    try:
        b = board_for(root)
        board_mod().board_text(b)
    finally:
        for p in stores:
            os.chmod(p.parent, stat.S_IRWXU)
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    assert len(b["agents"]) == 2
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in stores} == before
    assert sorted(x.name for x in stores[0].parent.iterdir()) == ["receipts.jsonl"]


def test_extra_sources_with_labels_and_globs(tmp_path, monkeypatch):
    root = make_root(tmp_path, ())
    other = make_root(tmp_path / "x", ("zeta",))
    z = Agent(other, "zeta", monkeypatch)
    z.lie()
    runs = tmp_path / "runs" / "qwen" / "B" / "r0"
    for task in ("t1", "t2"):
        (runs / task).mkdir(parents=True)
        (runs / task / "receipts.jsonl").write_bytes(z.store.read_bytes())
    B = board_mod()
    spec = os.pathsep.join([f"arena-B={tmp_path}/runs/*/B", f"{other}/profiles/zeta"])
    srcs = B.discover_sources(root=root, extra=B.parse_sources(spec))
    by = {s.label: s for s in srcs}
    assert set(by) == {"arena-B", "zeta"}
    assert len(by["arena-B"].paths) == 2
    b = B.build_board(srcs)
    names = {r["name"]: r for r in b["agents"]}
    assert names["arena-B"]["replies"] == 2  # an explicit label names the agent, whatever the record says
    assert names["zeta"]["replies"] == 1


# ---- filters and hall of cap ---------------------------------------------------------------------------
def test_filters_by_agent_model_and_skill(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    a, b_ = Agent(root, "alpha", monkeypatch), Agent(root, "beta", monkeypatch)
    a.lie(model="m-1", skills=["s1"])
    a.honest(model="m-2")
    b_.lie(model="m-2", skills=["s1", "s2"])
    assert [r["name"] for r in board_for(root, agent="alpha")["agents"]] == ["alpha"]
    fm = board_for(root, model="m-2")
    assert sorted(r["name"] for r in fm["agents"]) == ["alpha", "beta"] and fm["totals"]["replies"] == 2
    fs = board_for(root, skill="s1")
    assert fs["totals"]["replies"] == 2 and sorted(s["name"] for s in fs["skills"]) == ["s1", "s2"]
    assert board_for(root, skill=board_mod().NO_SKILL)["totals"]["replies"] == 1
    opts = fs["options"]  # the dropdowns always list everything, whatever is filtered
    assert opts["agents"] == ["alpha", "beta"] and opts["models"] == ["m-1", "m-2"] and opts["skills"][:2] == ["s1", "s2"]


def test_hall_of_cap_is_latest_first_quoted_and_redacted(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.turn("All tests pass.", [("pytest -q", "3 failed, 41 passed", 1)])
    a.honest()
    a.turn("All tests pass.", [("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789 pytest -q",
                                "2 failed, 42 passed", 1)])
    hall = board_for(root)["hall"]
    assert len(hall) == 2
    assert "2 failed" in hall[0]["evidence"] and "3 failed" in hall[1]["evidence"]
    assert hall[0]["claim"] == "All tests pass." and hall[0]["agent"] == "alpha" and hall[0]["kind"] == "tests"
    assert "ghp_abcdef" not in json.dumps(hall)


def test_hall_redacts_again_at_render_time(tmp_path):
    """A store written by an older/other build might hold an unredacted string: the board masks it anyway."""
    p = tmp_path / "receipts.jsonl"
    rec = {"type": "reply", "ts": time.time(), "model": "m", "receipts": [
        {"kind": "tests", "verdict": "CAP", "text": "password=hunter2hunter2 tests pass",
         "quote": "token ghp_abcdefghijklmnopqrstuvwxyz0123456789 1 failed", "cmd": "pytest", "cite": 1}]}
    p.write_text(json.dumps(rec) + "\n")
    B = board_mod()
    b = B.build_board(B.discover_sources(root=tmp_path / "none", extra=B.parse_sources(f"x={p}")))
    blob = json.dumps(b["hall"])
    assert "hunter2hunter2" not in blob and "ghp_abcdef" not in blob


# ---- incremental cache -------------------------------------------------------------------------------------
def test_cache_picks_up_appends_and_truncation(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    a.lie()
    B = board_mod()
    B.clear_cache()
    srcs = B.discover_sources(root=root)
    assert B.build_board(srcs)["totals"]["replies"] == 1
    a.honest()
    assert B.build_board(srcs)["totals"]["replies"] == 2
    a.ctx.commands["nocap"]("purge")
    assert B.build_board(B.discover_sources(root=root))["totals"]["replies"] == 0
    a.lie()
    assert B.build_board(B.discover_sources(root=root))["totals"]["replies"] == 1


# ---- /capscore board ---------------------------------------------------------------------------------------
def test_capscore_board_command(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    a, b_ = Agent(root, "alpha", monkeypatch), Agent(root, "beta", monkeypatch)
    for i in range(10):
        (b_.lie if i < 4 else b_.honest)(skills=["tdd"])
    a.lie()
    board_mod().clear_cache()
    a.ctx.settings["board.team_profiles"] = "all"  # the multi-profile view is opt-in (tests/test_board_scope.py)
    out = a.ctx.commands["capscore"]("board", session_id="", platform="cli")
    assert "Cap Board" in out
    lines = out.splitlines()
    beta = next(l for l in lines if "beta" in l and "40%" in l)
    assert beta.lstrip().startswith("1.")
    assert any("alpha" in l and "n=1" in l for l in lines)
    assert "Hall of Cap" in out and "tdd" in out


# ---- performance ---------------------------------------------------------------------------------------------
def test_10k_records_under_200ms(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta", "gamma"))
    a = Agent(root, "alpha", monkeypatch)
    a.lie(skills=["github-pr-workflow"])
    a.honest(skills=["tdd"])
    templates = [json.loads(l) for l in a.store.read_text().splitlines()]
    now = time.time()
    for k, name in enumerate(("alpha", "beta", "gamma")):
        store = home_of(root, name) / "plugin-data" / "agent-plugin-no-cap-4890e304" / "receipts.jsonl"
        store.parent.mkdir(parents=True, exist_ok=True)
        with open(store, "w") as fh:
            for i in range(3334 if k < 2 else 3332):
                rec = dict(templates[i % 2], ts=now - (i % 20) * DAY, model=f"m-{i % 4}", profile=name)
                fh.write(json.dumps(rec) + "\n")
    B = board_mod()
    B.clear_cache()
    srcs = B.discover_sources(root=root)
    # Same clock and calibration as the ReDoS budget (tests/test_redos.py): CPU time, best of five cold reads (cache
    # cleared each time), budget scaled by how much slower this machine is right now than the one it was set on
    # (capped at 4x), one retry after a pause. A loaded Mac stretches the run without the board doing more work.
    from test_redos import _calibration

    def best_cold():
        colds = []
        for _ in range(5):
            B.clear_cache()
            w0, t0 = time.perf_counter(), time.process_time()
            out = B.build_board(srcs)
            colds.append((time.process_time() - t0, time.perf_counter() - w0))
        return min(colds), out

    (cold, cold_wall), b = best_cold()
    scale = _calibration()
    if cold >= 0.200 * scale:
        time.sleep(1)
        (cold, cold_wall), b = best_cold()
        scale = _calibration()
    assert b["totals"]["replies"] == 10000 and b["totals"]["claims"] == 10000
    size = sum(p.stat().st_size for s in srcs for p in s.paths)
    t0 = time.process_time()
    B.build_board(B.discover_sources(root=root), model="m-1")
    warm = time.process_time() - t0
    print(f"10k records ({size / 1e6:.1f} MB): cold {cold * 1000:.0f} ms CPU ({cold_wall * 1000:.0f} ms wall), "
          f"warm+filter {warm * 1000:.0f} ms CPU, machine scale {scale:.2f}")
    assert cold < 0.200 * scale, f"cold board took {cold * 1000:.0f} ms CPU (budget {200 * scale:.0f} ms)"
    assert warm < 0.100 * scale


# ---- dashboard surface ----------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_manifest_declares_a_tab_with_existing_files():
    m = json.loads((ROOT / "dashboard" / "manifest.json").read_text())
    assert m["name"] == "no-cap" and m["label"] and m["tab"]["path"].startswith("/") and not m["tab"].get("hidden")
    for key in ("entry", "css", "api"):
        assert (ROOT / "dashboard" / m[key]).is_file(), key
    js = (ROOT / "dashboard" / m["entry"]).read_text()
    assert 'register("no-cap"' in js and "/api/plugins/no-cap/board" in js
    assert "WebSocket" not in js and "EventSource" not in js  # polls: works under plugins.isolation: host too


def _api(monkeypatch, root):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import importlib.util
    import sys
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    for k in [k for k in sys.modules if k.startswith("no_cap_dashboard")]:
        del sys.modules[k]
    spec = importlib.util.spec_from_file_location("no_cap_dashboard_api_test", ROOT / "dashboard" / "plugin_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("HERMES_HOME", str(root))
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/plugins/no-cap")
    client = TestClient(app)
    client.api_module = mod
    return client


def test_dashboard_api_serves_the_board_and_short_circuits_unchanged_polls(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha", "beta"))
    a = Agent(root, "alpha", monkeypatch)
    for _ in range(10):
        a.lie(skills=["tdd"])
    Agent(root, "beta", monkeypatch).honest()
    client = _api(monkeypatch, root)
    monkeypatch.setattr(client.api_module, "_settings", lambda: {"board": {"team_profiles": "all"}})  # opt-in
    r = client.get("/api/plugins/no-cap/board")
    assert r.status_code == 200
    b = r.json()
    assert [x["name"] for x in b["agents"]] == ["alpha", "beta"] and b["agents"][0]["cap_rate"] == 1.0
    assert b["hall"] and b["hall"][0]["agent"] == "alpha"
    again = client.get("/api/plugins/no-cap/board", params={"v": b["version"]}).json()
    assert again == {"unchanged": True, "version": b["version"]}
    a.lie()
    fresh = client.get("/api/plugins/no-cap/board", params={"v": b["version"]}).json()
    assert fresh.get("unchanged") is None and fresh["totals"]["replies"] == 12
    f = client.get("/api/plugins/no-cap/board", params={"agent": "beta"}).json()
    assert [x["name"] for x in f["agents"]] == ["beta"] and f["options"]["agents"] == ["alpha", "beta"]


def test_failed_skill_load_is_not_a_skill(tmp_path, monkeypatch):
    root = make_root(tmp_path, ("alpha",))
    a = Agent(root, "alpha", monkeypatch)
    sid, tid = "s-alpha", "tx"
    a.ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "nope"},
                                  result='{"success": false, "error": "Skill not found"}', session_id=sid, turn_id=tid)
    a.ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "tdd"}, result='{"success": true}',
                                  session_id=sid, turn_id=tid)
    a.ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": "pytest -q"},
                                  result=json.dumps({"output": "1 passed", "exit_code": 0}), session_id=sid, turn_id=tid)
    a.ctx.hooks["transform_llm_output"](response_text="All tests pass.", session_id=sid, turn_id=tid, model="m",
                                        platform="cli")
    assert json.loads(a.store.read_text().splitlines()[-1])["skills"] == ["tdd"]


def test_dashboard_router_mounts_only_known_route_modules(monkeypatch):
    """dashboard/plugin_api.py is the plugin's one router: it serves /board and mounts the fixed list of feature route
    modules beside it (desktop_api.py) when they exist, so features merge without editing this file."""
    pytest.importorskip("fastapi")
    import importlib.util
    spec = importlib.util.spec_from_file_location("no_cap_dashboard_api_routes", ROOT / "dashboard" / "plugin_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._ROUTE_MODULES == ("desktop_api",)
    paths = {r.path for r in mod.router.routes}
    assert "/board" in paths
    if not (ROOT / "dashboard" / "desktop_api.py").is_file():
        assert paths == {"/board"}
