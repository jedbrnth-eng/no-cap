"""Cap Coach: pattern miner, fix generator, approve/revert, injection scoping, measurement maths, fail-open."""
import json
import math
import os
import time

import pytest

from nocap import coach as C
from test_plugin import FakeCtx, load_plugin, reply, tool

T0 = 1_700_000_000.0
DAY = 86400


def rec(receipts, ts=T0, model="m-a", skills=None, session="s1"):
    return {"type": "reply", "ts": ts, "session_id": session, "model": model, "skills": skills or [],
            "receipts": receipts}


def rc(kind="tests", verdict="NO_RECEIPT", why="", cmd="", text="All tests pass."):
    return {"kind": kind, "verdict": verdict, "why": why, "cmd": cmd, "text": text, "tool": "terminal" if cmd else None,
            "claim": {"kind": kind}}


SUBSET = dict(why="only a subset of the tests ran", cmd="python -m pytest -q -k money")
STALE = dict(why="code changed after the last test run", cmd="python -m pytest -q")
PROVEN = dict(verdict="NO_CAP", cmd="python -m pytest -q")


# ---- classify / miner ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("r,pid", [
    (rc(verdict="CAP", why="the latest run of that suite failed"), "tests.failed_run"),
    (rc(**SUBSET), "tests.subset_only"),
    (rc(why="the claim also covers the full suite"), "tests.subset_only"),
    (rc(**STALE), "tests.stale_after_edit"),
    (rc(why="no run of that scope after the last code edit"), "tests.stale_after_edit"),
    (rc(why="no test run in this turn"), "tests.no_run"),
    (rc(why="only the agent's own check script ran, not the test suite"), "tests.no_run"),
    (rc(why="that run's output was cut by a pipe; other crates/packages may be hidden"), "tests.hidden_result"),
    (rc(why="no run shows 12 passed"), "tests.count_mismatch"),
    (rc(why="runs with mixed results; can't tell which one the claim means"), "tests.mixed_results"),
    (rc(why="a test was marked skip after a failing run"), "tests.skip_after_fail"),
    (rc(kind="pushed", why="no git push in this turn"), "pushed.no_push"),
    (rc(kind="pushed", verdict="CAP", why="push went to dev, not main"), "pushed.wrong_ref"),
    (rc(kind="merged", why="no merge of #4 in this turn"), "merged.no_merge"),
    (rc(kind="url", why="URL not fetched in this turn"), "url.unchecked"),
    (rc(kind="sha", why="SHA not in any tool output"), "sha.unseen"),
])
def test_classify_maps_each_receipt_shape(r, pid):
    assert C.classify(r) == pid


def test_classify_ignores_proven_and_unknown():
    assert C.classify(rc(**PROVEN)) is None
    assert C.classify(rc(kind="weather", why="?")) is None


def test_every_pattern_has_a_rule_and_a_why():
    for p in C.PATTERNS:
        assert p["rule"].strip() and p["why"].strip() and p["title"].strip()
    assert len({p["id"] for p in C.PATTERNS}) == len(C.PATTERNS)


def test_miner_clusters_counts_and_rate():
    recs = [rec([rc(**SUBSET)], ts=T0 + i) for i in range(6)] + [rec([rc(**PROVEN)], ts=T0 + 10 + i) for i in range(4)]
    recs.append(rec([rc(**STALE)], ts=T0 + 20))
    pats = C.mine(recs)
    top = pats[0]
    assert top["pattern"] == "tests.subset_only" and top["count"] == 6
    assert top["replies_in_scope"] == 11 and math.isclose(top["rate"], 6 / 11)
    assert top["runners"] == {"pytest": 6} and len(top["examples"]) == C.EXAMPLES
    assert {g["pattern"] for g in pats} == {"tests.subset_only", "tests.stale_after_edit"}


def test_miner_counts_a_reply_once_per_pattern():
    pats = C.mine([rec([rc(**SUBSET), rc(**SUBSET, text="The suite is green.")])])
    assert pats[0]["count"] == 1


def test_miner_splits_by_model_and_skill():
    recs = [rec([rc(**SUBSET)], model="a") for _ in range(3)] + [rec([rc(**SUBSET)], model="b", skills=["tdd"])]
    keys = {(g["model"], g["skill"]): g["count"] for g in C.mine(recs)}
    assert keys == {("a", "*"): 3, ("b", "tdd"): 1}


def test_miner_redacts_examples_and_skips_other_record_types():
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    recs = [rec([rc(why="no git push in this turn", kind="pushed", text=f"Pushed with token {secret}")]),
            {"type": "cap", "ts": T0, "receipts": [rc(**SUBSET)]}]
    pats = C.mine(recs)
    assert len(pats) == 1 and secret not in json.dumps(pats)


# ---- generator --------------------------------------------------------------------------------------------------
def _pattern(n=6, skill="*", model="m-a"):
    recs = [rec([rc(**SUBSET)], model=model, skills=[] if skill == "*" else [skill]) for _ in range(n)]
    return C.mine(recs)[0]


def test_generator_gives_rule_why_and_variants():
    prop = C.generate(_pattern(), agent="default")
    assert prop["id"].startswith("cc-") and prop["pattern"] == "tests.subset_only"
    assert "full suite" in prop["rule"] and "summary line" in prop["rule"]
    assert "Evidence: 6 of 6" in prop["why"]
    assert set(prop["variants"]) == {"rule", "memory"}  # no skill → no skill patch
    assert C.marker(prop["id"]) in prop["variants"]["memory"]["text"]


def test_generator_skill_patch_is_an_exact_diff_and_never_writes(tmp_path):
    sk = tmp_path / "skills" / "software-development" / "tdd"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: tdd\n---\n# TDD\n")
    before = (sk / "SKILL.md").read_text()
    prop = C.generate(_pattern(skill="tdd"), agent="default", skills_dir=tmp_path / "skills")
    v = prop["variants"]["skill"]
    assert v["path"].endswith("tdd/SKILL.md")
    assert v["diff"].startswith("--- a/SKILL.md") and "+## Receipts (No Cap coach" in v["diff"]
    assert (sk / "SKILL.md").read_text() == before


def test_generator_missing_skill_falls_back_to_text(tmp_path):
    prop = C.generate(_pattern(skill="ghost"), skills_dir=tmp_path)
    assert prop["variants"]["skill"]["diff"] == "" and "## Receipts" in prop["variants"]["skill"]["section"]


def test_proposal_id_is_stable():
    assert C.proposal_id("tests.subset_only", "m", "*", "default") == C.proposal_id("tests.subset_only", "m", "*",
                                                                                     "default")
    assert C.proposal_id("tests.subset_only", "m", "*", "a") != C.proposal_id("tests.subset_only", "m", "*", "b")


# ---- measurement maths ------------------------------------------------------------------------------------------
def test_wilson_known_values():
    lo, hi = C.wilson(5, 10)
    assert math.isclose(lo, 0.2366, abs_tol=1e-3) and math.isclose(hi, 0.7634, abs_tol=1e-3)
    lo, hi = C.wilson(0, 10)
    assert lo == 0.0 and math.isclose(hi, 0.2775, abs_tol=1e-3)
    assert C.wilson(0, 0) == (0.0, 1.0)


def test_two_proportion_known_value():
    t = C.two_proportion(30, 50, 15, 50)  # 0.6 vs 0.3: z = 3.015, p = 0.0026
    assert math.isclose(t["z"], 3.0151, abs_tol=1e-3) and math.isclose(t["p"], 0.00257, abs_tol=2e-4)
    assert C.two_proportion(0, 10, 0, 10)["p"] == 1.0
    assert C.two_proportion(1, 0, 1, 10)["p"] == 1.0


def test_mcnemar_exact():
    assert math.isclose(C.mcnemar(8, 1)["p"], 0.0390625)
    assert C.mcnemar(0, 0)["p"] == 1.0
    assert C.mcnemar(3, 3)["p"] == 1.0


def test_measure_not_enough_data_then_rates():
    prop = {"pattern": "tests.subset_only", "scope": {"model": "*", "skill": "*"}, "approved_ts": T0,
            "baseline": {"n": 12, "k": 6}}
    few = [rec([rc(**PROVEN)], ts=T0 + i) for i in range(3)]
    m = C.measure(prop, few, min_sample=10)
    assert not m["enough"] and "not enough data yet" in C.fmt_measure(m) and "after n=3" in C.fmt_measure(m)
    many = [rec([rc(**PROVEN)], ts=T0 + i) for i in range(11)] + [rec([rc(**SUBSET)], ts=T0 + 50)]
    m = C.measure(prop, many, min_sample=10)
    assert m["enough"] and m["after"] == {"n": 12, "k": 1, "rate": 1 / 12, "ci": C.wilson(1, 12)}
    assert m["test"]["p"] < 0.05 and "better" in C.fmt_measure(m)


def test_measure_stops_at_revert_and_respects_scope():
    prop = {"pattern": "tests.subset_only", "scope": {"model": "m-a", "skill": "*"}, "approved_ts": T0,
            "reverted_ts": T0 + 100, "baseline": {"n": 0, "k": 0}}
    recs = [rec([rc(**SUBSET)], ts=T0 + 1), rec([rc(**SUBSET)], ts=T0 + 200),
            rec([rc(**SUBSET)], ts=T0 + 2, model="other"), rec([rc(kind="pushed", why="no git push")], ts=T0 + 3)]
    assert C.measure(prop, recs, 1)["after"]["n"] == 1


# ---- coach object: settings, scan, approve, revert, injection ---------------------------------------------------
class Env:
    def __init__(self, tmp_path, cfg=None, inject_ok=True, home_name="home"):
        self.home = tmp_path / home_name
        self.data = self.home / "plugin-data" / "no-cap"
        self.cfg = {"coach": dict(cfg or {})}
        self.recs = []
        self.sent = []
        self.inject_ok = inject_ok
        self.c = C.Coach(lambda: self.data, lambda k, d=None: self.cfg.get(k, d), lambda: self.recs,
                         lambda: self.home, self.inject)

    def inject(self, text, key=""):
        self.sent.append(text)
        return self.inject_ok


def test_settings_defaults_and_auto_alias():
    s = C.settings(lambda k, d=None: d)
    assert s["mode"] == "suggest" and s["min_evidence"] == 5 and s["auto_after_caps"] == 5
    s = C.settings(lambda k, d=None: {"mode": "auto-suggest-after-8-caps", "min_evidence": "x"})
    assert s["mode"] == "auto" and s["auto_after_caps"] == 8 and s["min_evidence"] == 5
    assert C.settings(lambda k, d=None: "garbage")["mode"] == "suggest"


def test_scan_needs_min_evidence(tmp_path):
    e = Env(tmp_path)
    e.recs = [rec([rc(**SUBSET)], ts=T0 + i) for i in range(4)]
    assert e.c.scan() == [] and "No pattern has 5+" in e.c.command(["scan"])
    e.recs.append(rec([rc(**SUBSET)], ts=T0 + 9))
    fresh = e.c.scan()
    assert len(fresh) == 1 and fresh[0]["status"] == "proposed"
    assert e.c.active_rules("m-a") == []  # drafts are never injected


def test_approve_freezes_baseline_and_injects_only_in_scope(tmp_path):
    e = Env(tmp_path)
    now = time.time()
    e.recs = [rec([rc(**SUBSET)], ts=now - 100 + i) for i in range(5)] + \
             [rec([rc(**PROVEN)], ts=now - 50 + i) for i in range(5)] + [rec([rc(**SUBSET)], ts=now - 40 * DAY)]
    pid = e.c.scan()[0]["id"]
    out = e.c.command(["approve", pid])
    assert "Approved" in out and "5/10" in out  # the 40-day-old cap is outside the 14-day window
    text, ids = e.c.context("m-a")
    assert ids == [pid] and "full suite" in text and "No Cap coach" in text
    assert e.c.context("another-model") == (None, [])
    assert "Reverted" in e.c.command(["revert", pid])
    assert e.c.context("m-a") == (None, [])
    assert "isn't active" in e.c.command(["revert", pid])
    assert "reverted" in e.c.status()


def test_skill_scoped_rule_only_when_that_skill_is_loaded(tmp_path):
    e = Env(tmp_path)
    e.recs = [rec([rc(**SUBSET)], skills=["tdd"]) for _ in range(5)]
    pid = e.c.scan()[0]["id"]
    e.c.approve(pid)
    assert e.c.context("m-a", skills=[])[1] == []
    assert e.c.context("m-a", skills=["tdd"])[1] == [pid]


def test_agent_scope_uses_profile_name(tmp_path):
    e = Env(tmp_path, home_name="profiles/coder")
    assert e.c.agent() == "coder"
    e.recs = [rec([rc(**SUBSET)]) for _ in range(5)]
    pid = e.c.scan()[0]["id"]
    e.c.approve(pid)
    data = e.c.store.load()
    data["proposals"][pid]["scope"]["agent"] = "someone-else"
    e.c.store.save(data)
    assert e.c.context("m-a")[1] == []


def test_mode_off_injects_nothing_and_max_rules_caps(tmp_path):
    e = Env(tmp_path, {"max_rules": 1})
    e.recs = [rec([rc(**SUBSET)]) for _ in range(5)] + [rec([rc(**STALE)]) for _ in range(5)]
    for p in e.c.scan():
        e.c.approve(p["id"])
    assert len(e.c.context("m-a")[1]) == 1
    e.cfg["coach"]["mode"] = "off"
    assert e.c.context("m-a") == (None, [])
    assert "off" in e.c.command(["scan"])


def test_dismiss_is_sticky_across_rescans(tmp_path):
    e = Env(tmp_path)
    e.recs = [rec([rc(**SUBSET)]) for _ in range(5)]
    pid = e.c.scan()[0]["id"]
    e.c.dismiss(pid)
    e.recs += [rec([rc(**SUBSET)]) for _ in range(5)]
    assert e.c.scan() == [] and e.c.get(pid)["status"] == "dismissed"


def test_memory_variant_shows_text_and_only_asks_agent_with_apply(tmp_path):
    e = Env(tmp_path)
    e.recs = [rec([rc(**SUBSET)]) for _ in range(5)]
    pid = e.c.scan()[0]["id"]
    out = e.c.approve(pid, "memory")
    assert "doesn't edit" in out and e.sent == [] and C.marker(pid) in out
    assert e.c.context("m-a")[1] == []  # a memory note isn't also injected as a rule
    assert "not applied yet" in e.c.status()
    e.c.approve(pid, "memory", apply=True)
    assert len(e.sent) == 1 and "memory tool" in e.sent[0] and "decline" in e.sent[0]
    assert "the agent was asked" in e.c.status()
    mem = e.home / "memories"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("x\n§\n" + e.c.get(pid)["variants"]["memory"]["text"])
    assert "in place" in e.c.status()


def test_skill_variant_apply_refused_falls_back_to_manual(tmp_path):
    e = Env(tmp_path, inject_ok=False)
    sk = e.home / "skills" / "tdd"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("# TDD\n")
    e.recs = [rec([rc(**SUBSET)], skills=["tdd"]) for _ in range(5)]
    pid = e.c.scan()[0]["id"]
    out = e.c.approve(pid, "skill", apply=True)
    assert "didn't let No Cap message the agent" in out and "+## Receipts" in out
    assert (sk / "SKILL.md").read_text() == "# TDD\n"
    assert "waiting for you" in e.c.status()
    assert "no rule" not in e.c.approve(pid, "nonsense")  # unknown variant is refused, not crashed
    assert "has no nonsense variant" in e.c.approve(pid, "nonsense")


def test_auto_mode_announces_once_and_applies_nothing(tmp_path):
    e = Env(tmp_path, {"mode": "auto-suggest-after-3-caps"})
    e.recs = [rec([rc(**SUBSET)]) for _ in range(3)]
    tip = e.c.maybe_announce([rc(**SUBSET)])
    assert tip and "not applied" in tip
    assert e.c.maybe_announce([rc(**SUBSET)]) is None
    assert e.c.active_rules("m-a") == []
    e.cfg["coach"]["mode"] = "suggest"
    e.recs += [rec([rc(**STALE)]) for _ in range(5)]
    assert e.c.maybe_announce([rc(**STALE)]) is None


# ---- fail-open --------------------------------------------------------------------------------------------------
def test_corrupt_coach_file_is_set_aside(tmp_path):
    e = Env(tmp_path)
    e.data.mkdir(parents=True)
    (e.data / "coach.json").write_text("{not json")
    assert e.c.context("m-a") == (None, [])
    assert (e.data / "coach.corrupt").exists()
    e.recs = [rec([rc(**SUBSET)]) for _ in range(5)]
    assert len(e.c.scan()) == 1
    assert oct(os.stat(e.data / "coach.json").st_mode & 0o777) == "0o600"


def test_plugin_pre_llm_call_fails_open(tmp_path, caplog):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    assert ctx.hooks["pre_llm_call"](session_id="s1", model="m") is None
    d = ctx.state.data_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "coach.json").mkdir()  # unreadable as a file: load raises inside the hook
    assert ctx.hooks["pre_llm_call"](session_id="s1", model="m") is None


def test_coach_error_never_changes_the_reply(tmp_path, monkeypatch):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"coach": {"mode": "auto"}})
    mod.register(ctx)

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("coach broke")
    monkeypatch.setattr(C.Coach, "maybe_announce", boom)
    for name in list(__import__("sys").modules):
        m = __import__("sys").modules[name]
        if name.endswith("nocap.coach") and hasattr(m, "Coach"):
            monkeypatch.setattr(m.Coach, "maybe_announce", boom)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.")
    assert "🧢 CAP" in out and calls == [1]


# ---- end to end through the plugin ------------------------------------------------------------------------------
def test_end_to_end_mine_approve_inject_measure(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"coach": {"min_sample": 3}})
    mod.register(ctx)
    for i in range(5):
        ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "tdd"}, result="{}",
                                    session_id=f"s{i}", turn_id="t", status="ok")
        tool(ctx, "python -m pytest -q -k money", "2 passed, 40 deselected in 0.1s", session=f"s{i}", turn="t")
        reply(ctx, "All tests pass.", session=f"s{i}", turn="t")
    lines = [json.loads(x) for x in (ctx.state.data_dir / "receipts.jsonl").read_text().splitlines()]
    assert lines[-1]["skills"] == ["tdd"] and lines[-1]["coach"] == []
    out = ctx.commands["cap"](raw_args="coach scan", session_id="s0")
    assert "Drafted 1" in out
    pid = out.split("• ")[1].split()[0]
    assert "only a subset" in ctx.commands["cap"](raw_args=f"coach show {pid}", session_id="s0")
    assert "Approved" in ctx.commands["cap"](raw_args=f"coach approve {pid}", session_id="s0")
    assert ctx.hooks["pre_llm_call"](session_id="new", model="demo/model-a") is None  # skill not loaded there
    ctx.hooks["post_tool_call"](tool_name="skill_view", args={"name": "tdd"}, result="{}", session_id="s9",
                                turn_id="t", status="ok")
    got = ctx.hooks["pre_llm_call"](session_id="s9", model="demo/model-a")
    assert pid in got["context"]
    tool(ctx, "python -m pytest -q", "42 passed in 0.3s", session="s9", turn="t")
    assert "🧾 NO CAP" in reply(ctx, "All tests pass.", session="s9", turn="t")
    last = json.loads((ctx.state.data_dir / "receipts.jsonl").read_text().splitlines()[-1])
    assert last["coach"] == [pid]
    status = ctx.commands["cap"](raw_args="coach status", session_id="s9")
    assert "after 0/1" in status and "not enough data yet" in status


def test_cli_coach_subcommand(tmp_path, capsys):
    import argparse
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    setup, handler = ctx.cli["nocap"]
    ap = argparse.ArgumentParser()
    setup(ap)
    handler(ap.parse_args(["coach", "approve", "cc-zzzzzz", "--apply"]))
    assert "No proposal cc-zzzzzz" in capsys.readouterr().out
    handler(ap.parse_args(["coach"]))
    assert "Cap Coach" in capsys.readouterr().out
