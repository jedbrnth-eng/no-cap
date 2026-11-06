"""`/nocap doctor` and `hermes nocap doctor`: reply-transform conflict, /cap injection opt-in, store writability."""
import os
import stat
import sys

import pytest

from test_plugin import FakeCtx, load_plugin, reply, tool


def doctor_mod():
    mod = load_plugin()
    return sys.modules[mod.__name__ + ".nocap.doctor"]


def run(tmp_path, home=None, entry=None, store=None, enabled=lambda n: None, show="default"):
    d = doctor_mod()
    return d.run(home or tmp_path / "home", "annotate", entry or {}, store or tmp_path / "data" / "receipts.jsonl",
                 [], enabled, show_uncertain=show)


def test_store_writable_is_checked_and_leaves_no_trace(tmp_path):
    out = run(tmp_path)
    assert "✅ Store writable" in out
    assert not [p for p in (tmp_path / "data").iterdir() if p.name != "receipts.jsonl"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_store_not_writable_is_an_error(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        out = run(tmp_path, store=ro / "receipts.jsonl")
    finally:
        ro.chmod(stat.S_IRWXU)
    assert "❌ Store not writable" in out and "1 problem" in out


def test_disabled_transform_owner_is_not_a_conflict(tmp_path):
    home = tmp_path / "home"
    other = home / "plugins" / "turn-usage"
    other.mkdir(parents=True)
    (other / "plugin.yaml").write_text("name: turn-usage\nprovides_hooks:\n  - transform_llm_output\n")
    assert "turn-usage" in run(tmp_path, home=home) and "1 problem" in run(tmp_path, home=home)
    quiet = run(tmp_path, home=home, enabled=lambda n: False)
    assert "No other plugin rewrites replies" in quiet and "0 problems" in quiet


def test_injection_opt_in_is_reported_both_ways(tmp_path):
    off = run(tmp_path)
    assert "allow_gateway_injection: true" in off and "paste" in off
    on = run(tmp_path, entry={"allow_gateway_injection": True})
    assert "✅ /cap may send its steer" in on


def test_reports_show_uncertain_level(tmp_path):
    assert "show_uncertain: default" in run(tmp_path)
    assert "show_uncertain: all" in run(tmp_path, show="all")


def test_slash_doctor_runs_through_the_plugin(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    reply(ctx, "All tests pass.")
    out = ctx.commands["nocap"]("doctor", session_id="s1")
    assert "No Cap doctor" in out and "show_uncertain: strict" in out and "Store writable" in out


def _cli_doctor(tmp_path, home_plugins=()):
    import argparse
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    for name in home_plugins:
        d = ctx.state.data_dir.parents[1] / "plugins" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "plugin.yaml").write_text(f"name: {name}\nprovides_hooks:\n  - transform_llm_output\n")
    mod.register(ctx)
    _, handler = ctx.cli["nocap"]
    return handler(argparse.Namespace(nocap_cmd="doctor"))


def test_cli_doctor_exit_code_is_zero_when_healthy(tmp_path, capsys):
    rc = _cli_doctor(tmp_path)
    assert "0 problems found" in capsys.readouterr().out
    assert rc in (0, None)


def test_cli_doctor_exit_code_is_non_zero_when_problems_are_found(tmp_path, capsys):
    rc = _cli_doctor(tmp_path, home_plugins=("turn-usage",))
    assert "1 problem found" in capsys.readouterr().out
    assert isinstance(rc, int) and rc != 0


def test_problem_count_is_returned_with_the_report(tmp_path):
    d = doctor_mod()
    text, n = d.check(tmp_path / "home", "annotate", {}, tmp_path / "data" / "receipts.jsonl", [], lambda n: None)
    assert n == 0 and "0 problems found" in text


def test_injection_hint_gives_the_exact_command(tmp_path):
    # Install proof (docs/media/install-run): a new user reads the hint, so it names the one command that turns it on.
    off = run(tmp_path)
    assert "hermes config set plugins.entries.no-cap.allow_gateway_injection true" in off
