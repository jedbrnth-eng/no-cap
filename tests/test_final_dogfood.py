"""Final dogfood round (0.2.1): issues seen on a real Hermes CLI session with a local Qwen3-30B-A3B.

1. /cap re-score: after a 🧢 on "All tests pass.", the agent answered the steer honestly with "3 failed, 41 passed"
   (no new tool call). The re-score line said `still 🤔 “All tests pass.” (tests)`: it matched the new, opposite
   claim by kind alone, so it named the old claim as still standing, and "still" hid that the verdict changed.
   A reply that now says the tests fail takes the pass claim back; a changed verdict says `was → now`.
2. /cap on the classic CLI with allow_gateway_injection on: Hermes routes the steer through the local gateway, the
   agent answers it (tools run, the reply is stored and re-scored) but nothing of that turn prints in the CLI, so
   the user saw "the next reply gets re-scored" and then nothing. /cap now says where the answer shows (/nocap),
   and the doctor says the same before the user turns injection on.
"""
from test_plugin import FakeCtx, load_plugin, reply, tool

from nocap import doctor


def _capped(tmp_path, **settings):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict", **settings})
    mod.register(ctx)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1)
    out = reply(ctx, "All tests pass.")
    assert "🧢 CAP" in out
    ctx.commands["cap"]("", session_id="s1")
    return ctx


def test_rescore_counts_an_admitted_failure_as_a_retraction(tmp_path):
    ctx = _capped(tmp_path)
    out = reply(ctx, "3 failed, 41 passed in 0.02s", turn="t2")
    line = next(l for l in out.splitlines() if "/cap re-score" in l)
    assert "retracted" in line, line
    assert "still" not in line, line


def test_rescore_still_caps_a_repeated_lie(tmp_path):
    ctx = _capped(tmp_path)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1, turn="t2")
    out = reply(ctx, "All tests pass.", turn="t2")
    line = next(l for l in out.splitlines() if "/cap re-score" in l)
    assert "still 🧢" in line, line


def test_rescore_names_a_changed_verdict(tmp_path):
    ctx = _capped(tmp_path, cross_turn=False)
    out = reply(ctx, "All tests pass.", turn="t2")  # restated with nothing run: no longer contradicted, not proven
    line = next(l for l in out.splitlines() if "/cap re-score" in l)
    assert "🧢 → 🤔" in line, line
    assert "still" not in line, line


def test_cap_on_the_classic_cli_says_where_the_answer_shows(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"}, inject_ok=True)
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.02s", 1)
    reply(ctx, "All tests pass.")
    msg = ctx.commands["cap"]("", session_id="s1", platform="cli")
    assert ctx.injected and "Cap called on 1 claim" in msg
    assert "/nocap" in msg, msg


def test_cap_elsewhere_keeps_the_short_message(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"}, inject_ok=True)
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.02s", 1)
    reply(ctx, "All tests pass.")
    msg = ctx.commands["cap"]("", session_id="s1", session_key="k", platform="desktop")
    assert "/nocap" not in msg, msg


def test_doctor_warns_that_the_classic_cli_hides_an_injected_answer(tmp_path):
    for entry in ({}, {"allow_gateway_injection": True}):
        out = doctor.run(tmp_path, "annotate", entry, tmp_path / "r.jsonl", [], lambda n: None)
        line = next(l for l in out.splitlines() if "allow_gateway_injection" in l)
        assert "classic CLI" in line and "/nocap" in line, line
