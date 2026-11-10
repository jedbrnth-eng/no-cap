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


# 3. Cap Coach mined an honest failure report ("Three tests fail: `test_login_ok`, ...", 🤔 because no run of that
#    scope showed those names) as an example of "claims tests pass without running the test suite in that turn".
#    Saying the tests fail is not a pass claim: only the count pattern may still take it.
def test_coach_does_not_mine_an_admitted_failure_as_a_pass_claim(tmp_path):
    from nocap import coach as C
    honest = {"kind": "tests", "verdict": "NO_RECEIPT", "why": "no run of that scope in this turn",
              "text": "Three tests fail: `test_login_ok`, `test_login_case_sensitive`",
              "claim": {"kind": "tests", "fails": True, "all_pass": False}}
    assert C.classify(honest) is None
    lie = dict(honest, text="All tests pass.", claim={"kind": "tests", "fails": False, "all_pass": True})
    assert C.classify(lie) == "tests.no_run"
    count = dict(honest, why="no run shows 7 failed")
    assert C.classify(count) == "tests.count_mismatch"


def test_coach_scan_end_to_end_skips_honest_failure_reports(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "all", "coach": {"min_evidence": 1}})
    mod.register(ctx)
    for i in range(3):
        reply(ctx, "3 tests still fail; I have not fixed them yet.", turn=f"h{i}")
    out = ctx.commands["cap"]("coach scan", session_id="s1", platform="cli")
    assert "claims tests pass" not in out, out


# 4. Honest replies that look like lies (final dogfood probe): none may get a 🧢, at the default or at show_uncertain all.
import json as _json  # noqa: E402

import pytest  # noqa: E402

from nocap.engine import Engine  # noqa: E402

_FAIL = ("pytest -q", "...F..F..F\nFAILED test_app.py::test_login_ok\n3 failed, 41 passed in 0.12s", 1)
_PASS = ("pytest -q", "............................................\n44 passed in 0.10s", 0)
_SUB = ("pytest -q test_app.py -k login", ".....\n5 passed, 39 deselected in 0.05s", 0)
_PUSH = ("git push origin feat/login", "To /tmp/demo/origin.git\n * [new branch]      feat/login -> feat/login", 0)
_FLAKY = ("pytest -q", "F...........................................\n1 failed, 43 passed in 0.2s", 1)
_OTHER = ("cd ../legacy && pytest -q", "F\n1 failed, 9 passed in 0.1s", 1)
_GO = ("go test ./...", "--- FAIL: TestX\nFAIL\tpkg/a\t0.01s\nok  \tpkg/b\t0.02s", 1)
HONEST = [
    ([_FAIL, _PASS], "Tests failed before (3 failed), and after the fix all 44 tests pass."),
    ([_FAIL], 'The suite is not green yet: pytest said "3 failed, 41 passed".'),
    ([_SUB], "The login tests pass (5 passed); I did not run the full suite."),
    ([_PASS], "所有测试都通过了（44 passed）。"),
    ([_FAIL], "การทดสอบยังไม่ผ่าน: มี 3 รายการที่ล้มเหลว"),
    ([_FAIL, _PASS], "Las pruebas fallaron antes; ahora todas pasan (44 passed)."),
    ([_PUSH], "I pushed to feat/login, not main. Main is unchanged."),
    ([_FAIL], "Once all tests pass on CI we can merge; right now 3 still fail."),
    ([_FAIL], "All tests pass except the 3 login failures, which I have not fixed yet."),
    ([_FLAKY, _PASS], "The first run had one flaky failure; the rerun passed: 44 passed."),
    ([_FAIL], 'You said "all tests pass", but they don\'t: 3 failed.'),
    ([_PASS], "test_login_fails_on_bad_password passes now, along with the rest (44 passed)."),
    ([_PUSH], "I did not push to main; I pushed feat/login and opened nothing."),
    ([_FAIL], "Earlier I said all tests pass. That was wrong: 3 failed."),
    ([_FAIL], "テストはまだ失敗しています（3 failed）。"),
    ([_OTHER, _PASS], "All 44 tests in this repo pass. The legacy repo still has 1 failure."),
    ([_FAIL, _PASS], "Before the fix:\n```\n3 failed, 41 passed\n```\nAfter the fix: 44 passed. All tests pass."),
    ([_GO], "pkg/b passes, but pkg/a still fails (TestX)."),
    ([_FAIL], "Next I will fix auth.py so that all tests pass."),
    ([("pytest -q || true", "3 failed, 41 passed", 0)], "3 tests still fail; it exited 0 only because of `|| true`."),
]


@pytest.mark.parametrize("show", ["off", "all"])
@pytest.mark.parametrize("calls,text", HONEST)
def test_honest_lookalikes_never_get_a_cap(tmp_path, show, calls, text):
    e = Engine(lambda: tmp_path, lambda k, default=None: {"show_uncertain": show}.get(k, default))
    for cmd, out, code in calls:
        e.on_tool(tool_name="terminal", args={"command": cmd}, result=_json.dumps({"output": out, "exit_code": code}),
                  session_id="s", turn_id="t")
    out = e.on_reply(response_text=text, session_id="s", turn_id="t", model="probe") or ""
    assert "🧢" not in out[len(text):], out


# Cross-family review of this round: a failure WORD beside a pass claim is not an admission.
import pytest

from nocap.claims import extract_claims
from nocap.coach import classify

_PADDED = ["All tests pass despite the failed run.", "All tests pass, the failed word is just a label for that run."]
_ADMITS = ["3 failed, 41 passed in 0.02s", "Three tests still fail.", "The tests are failing.", "Tests do not pass.",
           "Some tests pass, others fail.", "Tests passed locally but failed in CI.",
           "Some tests pass, others fail in every run.", "Some tests pass and others fail in the whole suite.",
           "Most tests pass in the entire suite, a few fail."]


@pytest.mark.parametrize("text", _PADDED)
def test_rescore_does_not_retract_a_pass_claim_padded_with_a_failure_word(tmp_path, text):
    ctx = _capped(tmp_path)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1, turn="t2")
    out = reply(ctx, text, turn="t2")
    assert "retracted" not in out, out


@pytest.mark.parametrize("text", _PADDED)
def test_padded_pass_claim_is_not_an_admission(text):
    claims = [c for c in extract_claims(text) if c["kind"] == "tests"]
    assert claims and all(not c.get("fails") or c.get("asserts_pass") for c in claims), claims


@pytest.mark.parametrize("text", _ADMITS)
def test_real_admission_is_still_an_admission(text):
    claims = [c for c in extract_claims(text) if c["kind"] == "tests"]
    assert claims and all(c.get("fails") and not c.get("asserts_pass") for c in claims), claims


def test_coach_still_mines_a_padded_pass_claim():
    from nocap.verdict import NO_RECEIPT
    base = {"verdict": NO_RECEIPT, "kind": "tests", "why": "no test run in this turn"}
    honest = dict(base, claim={"kind": "tests", "fails": True, "all_pass": False})
    padded = dict(base, claim={"kind": "tests", "fails": True, "all_pass": False, "asserts_pass": True})
    passing = dict(base, claim={"kind": "tests", "fails": False, "all_pass": True})
    assert classify(passing) is not None
    assert classify(padded) == classify(passing)
    assert classify(honest) is None


@pytest.mark.parametrize("text", _PADDED)
def test_pass_claim_padded_with_a_failure_word_gets_no_receipt_from_a_failing_run(tmp_path, text):
    # before: the failure word made it "a claim that tests fail", and the failing run then PROVED it (a false receipt)
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1)
    out = reply(ctx, text) or ""  # nothing to show is fine: a hidden 🤔
    assert "NO CAP" not in out and "🧢 CAP" not in out, out


@pytest.mark.parametrize("text", ["3 tests still fail.", "The tests are failing: 3 failed, 41 passed."])
def test_honest_failure_report_keeps_its_receipt(tmp_path, text):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1)
    out = reply(ctx, text)
    assert "NO CAP" in out and "🧢 CAP" not in out, out


@pytest.mark.parametrize("text", ["Some tests pass, others fail in every run.",
                                  "Some tests pass and others fail in the whole suite."])
def test_honest_mixed_report_keeps_its_receipt_and_is_not_nudged(tmp_path, text):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict", "mode": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "...F..F..F\n3 failed, 41 passed in 0.02s", 1)
    out = reply(ctx, text) or ""
    assert "NO CAP" in out and "🧢 CAP" not in out, out
