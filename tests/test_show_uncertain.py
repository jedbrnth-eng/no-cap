"""🤔 noise control: `show_uncertain` = off (the default) | strict | expected | all.

off (default): 🤔 is never stamped; unsure claims are recorded and /nocap all and /cap still see them. On a fresh blind
sample the strict level's visible 🤔 were right 0 times out of 6 (each was proven by the agent's own check script),
and the fix for that has no fresh labelled sample behind it yet, so visible 🤔 is opt-in.
strict: a 🤔 is stamped only on a "tests pass" claim in a turn that ran no tests, showed no test output and ran no
check script of the agent's own. The wider `expected` level was right 0 times out of 12 on unseen runs.
expected: a 🤔 is stamped when a receipt was expected for that claim type AND nothing relevant ran this turn.
Subset, scope, lint, unparsed-runner, disabled-🧢 and other "something ran but it's unclear" cases never get a stamp
below `all`. They are still written to the ledger and show up in /nocap all and /cap.
"""
import json

from test_plugin import FakeCtx, load_plugin, reply, tool


def make(tmp_path, **settings):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, settings)
    mod.register(ctx)
    return ctx


def records(ctx):
    p = ctx.state.data_dir / "receipts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_default_is_off(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "ls", "auth.py test_app.py")
    assert reply(ctx, "All tests pass.") is None
    assert records(ctx)[-1]["receipts"][0]["hidden"] is True
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.5s", 1, turn="t2")
    assert "🧢 CAP" in reply(ctx, "All tests pass.", turn="t2")


def test_strict_stamps_tests_claim_when_no_test_command_ran(tmp_path):
    ctx = make(tmp_path, show_uncertain="strict")
    tool(ctx, "ls", "auth.py test_app.py")
    out = reply(ctx, "All tests pass.")
    assert "🤔 NO RECEIPT" in out and "no test run in this turn" in out


def test_default_hides_subset_run_but_records_it(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q tests/test_auth.py", "")  # a scoped run with no parsed summary: unclear
    out = reply(ctx, "All tests pass.")
    assert out is None  # nothing stamped, reply untouched
    recs = records(ctx)
    assert recs and recs[-1]["receipts"][0]["verdict"] == "NO_RECEIPT"
    assert recs[-1]["receipts"][0]["hidden"] is True
    listing = ctx.commands["nocap"]("all", session_id="s1")
    assert "NO RECEIPT" in listing and "not stamped" in listing


def test_hidden_claims_are_still_capable(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q tests/test_auth.py", "")
    reply(ctx, "All tests pass.")
    msg = ctx.commands["cap"]("", session_id="s1")
    assert "Cap called" in msg
    assert ctx.injected and "All tests pass." in ctx.injected[-1]


def test_all_shows_every_uncertain_stamp(tmp_path):
    ctx = make(tmp_path, show_uncertain="all")
    tool(ctx, "pytest -q tests/test_auth.py", "")
    out = reply(ctx, "All tests pass.")
    assert "🤔 NO RECEIPT" in out


def test_off_never_stamps_uncertain_but_keeps_cap_and_proof(tmp_path):
    ctx = make(tmp_path, show_uncertain="off")
    out = reply(ctx, "All tests pass.")
    assert out is None
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.5s", 1, turn="t2")
    out = reply(ctx, "All tests pass. Deployed to production.", turn="t2")
    assert "🧢 CAP" in out and "🤔" not in out
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t3")
    assert "🧾 NO CAP" in reply(ctx, "All tests pass.", turn="t3")


def test_unknown_value_falls_back_to_default(tmp_path):
    ctx = make(tmp_path, show_uncertain="loud")
    assert reply(ctx, "All tests pass.") is None
    tool(ctx, "pytest -q tests/test_auth.py", "", turn="t2")
    assert reply(ctx, "All tests pass.", turn="t2") is None


def test_default_hides_disabled_cap_contradictions(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "make build", "error: boom", 2)
    out = reply(ctx, "The build succeeds.")
    assert out is None or "🤔" not in out


def test_default_hides_sha_recall_with_no_output(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "ls", "x")
    out = reply(ctx, "That landed in commit 3f9a2b1c earlier.")
    assert out is None or "🤔" not in out


def test_footer_counts_and_cap_hint_follow_what_is_shown(tmp_path):
    ctx = make(tmp_path, show_uncertain="expected")
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    tool(ctx, "pytest -q tests/a.py", "")
    out = reply(ctx, "All tests pass. Deployed to production.")
    assert "🧾" in out and "🤔 1 no receipt" in out  # deploy: nothing ran → shown
    ctx2 = make(tmp_path / "b")
    tool(ctx2, "pytest -q", "44 passed in 0.5s")
    out2 = reply(ctx2, "All tests pass. That's commit 3f9a2b1c.")
    assert "🤔" not in out2 and "/cap and the agent" not in out2


def test_expected_stamps_push_with_no_push(tmp_path):
    ctx = make(tmp_path, show_uncertain="expected")
    tool(ctx, "git status", "On branch feat/login")
    out = reply(ctx, "Pushed to main.")
    assert "🤔 NO RECEIPT" in out and "no git push" in out


def test_footer_drops_markdown_bold_on_the_classic_cli(tmp_path):
    ctx = make(tmp_path)  # the CLI prints the appended footer raw, so "**Receipts**" showed its asterisks
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    out = reply(ctx, "All tests pass.")  # helper sends platform="cli"
    assert "**" not in out.split("All tests pass.", 1)[1] and "Receipts · 🧾 1 no cap" in out
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t2")
    d = ctx.hooks["transform_llm_output"](response_text="All tests pass.", session_id="s1", model="m",
                                          platform="discord", turn_id="t2")
    assert "**Receipts**" in d


def test_strict_is_tests_claims_with_zero_test_runs_only(tmp_path):
    ctx = make(tmp_path, show_uncertain="strict")
    tool(ctx, "git status", "On branch feat/login")
    out = reply(ctx, "All tests pass. Pushed to main. Deployed to production.")
    assert "🤔 NO RECEIPT" in out and "no test run in this turn" in out
    assert "no git push" not in out and "no deploy" not in out
    recs = records(ctx)[-1]["receipts"]
    assert {r["kind"]: r["hidden"] for r in recs} == {"tests": False, "pushed": True, "deployed": True}


def test_default_alias_and_off_are_the_same(tmp_path):
    for i, level in enumerate(("default", "off", "")):
        ctx = make(tmp_path / str(i), show_uncertain=level)
        tool(ctx, "git status", "clean")
        assert reply(ctx, "All tests pass. Pushed to main.") is None, level


def test_strict_hides_tests_claim_when_a_check_script_ran(tmp_path):
    ctx = make(tmp_path, show_uncertain="strict")
    tool(ctx, "python reproduce.py", "fixed: True")
    assert reply(ctx, "All tests pass.") is None


def test_strict_hides_tests_claim_when_test_output_was_seen(tmp_path):
    ctx = make(tmp_path, show_uncertain="strict")
    tool(ctx, "cat /tmp/test.log", "===== 44 passed in 1.2s =====")
    assert reply(ctx, "All tests pass.") is None


def test_strict_hides_failure_claims_with_no_run(tmp_path):
    ctx = make(tmp_path, show_uncertain="strict")
    tool(ctx, "ls", "x")
    assert reply(ctx, "Two tests are still failing.") is None
