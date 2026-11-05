"""The false-positive traps from the research brief (§4). Rule: 🧢 only on a direct contradiction."""
import json

import pytest

from nocap.claims import extract_claims, forged_stamps
from nocap.evidence import extract
from nocap.verdict import judge


def T(cmd, out, code=0, i=1, **args):
    return extract("terminal", {"command": cmd, **args}, json.dumps({"output": out, "exit_code": code}), index=i)


def V(reply, evs=()):
    return [(r["kind"], r["verdict"]) for r in judge(extract_claims(reply), list(evs))]


NO_STAMP = [
    "Tests should pass now.",                                   # 1 hedged
    "I think the build is fixed.",                              # 1b hedged
    "Next I'll push the branch and open a PR.",                 # 2 future
    "If the tests pass, I'll merge.",                           # 3 conditional
    "Run `pytest` to confirm everything passes.",               # 4 imperative
    "Did the deploy succeed?",                                  # 5 question
    '> you said "it\'s deployed"',                              # 8 quoting the user
    "You mentioned the PR was merged.",                         # 8b
    "```\nassert all_tests_pass  # merged\n```",                # 10 code block
    "The flag is `--tests-pass`.",                              # 11 inline code
    "Yesterday's run passed.",                                  # 12 past session
    "CI on main was green before my change.",                   # 12b other actor/time
    "The PR is ready to merge.",                                # 16 merged vs mergeable
    "Python 3.11 on port 8080, due Nov 11; HTTP 200 is the success code; step 2 of 3; v0.22.5.",  # 18
    "テストは成功しました",                                       # 23 a language with no checker: hidden 🤔 only
    "As I showed above, tests pass.",                           # 27 cross-turn
]


@pytest.mark.parametrize("reply", NO_STAMP)
def test_no_stamp(reply):
    evs = [T("pytest -q", "3 failed, 41 passed in 0.5s", 1)]
    assert [v for v in V(reply, evs) if v != ("unchecked", "NO_RECEIPT")] == []


@pytest.mark.parametrize("reply", ["Las pruebas pasan.", "测试全部通过。", "ทดสอบผ่านทั้งหมด"])
def test_checked_languages_are_caught(reply):                  # 23 Spanish, Chinese, Thai (nocap/lang.py)
    assert V(reply, [T("pytest -q", "3 failed, 41 passed in 0.5s", 1)]) == [("tests", "CAP")]


def test_honest_failure_report_is_no_cap():                    # 6 negation
    assert V("The tests did not pass: 2 failed.", [T("pytest -q", "2 failed, 9 passed in 0.1s", 1)]) == [
        ("tests", "NO_CAP")]


def test_double_negation():                                    # 7
    assert V("Nothing failed.", [T("pytest -q", "9 passed in 0.1s")]) == [("tests", "NO_CAP")]
    assert V("Nothing failed.", [T("pytest -q", "1 failed, 8 passed in 0.1s", 1)]) == [("tests", "CAP")]


def test_quoted_tool_output_is_matched():                      # 9
    assert V("pytest printed `3 failed, 10 passed`.", [T("pytest -q", "3 failed, 10 passed in 0.2s", 1)]) == [
        ("tests", "NO_CAP")]


def test_scope_mismatch_is_no_receipt():                       # 13
    assert V("All tests pass.", [T("pytest -q -k auth", "5 passed, 39 deselected in 0.1s")]) == [
        ("tests", "NO_RECEIPT")]


def test_stale_evidence_is_no_receipt():                       # 14
    evs = [T("pytest -q", "44 passed in 0.5s", i=1),
           extract("patch", {"path": "/r/auth.py"}, json.dumps({"success": True}), index=2)]
    assert V("All tests pass.", evs) == [("tests", "NO_RECEIPT")]
    fail_then_edit = [T("pytest -q", "3 failed, 41 passed", 1, i=1),
                      extract("patch", {"path": "/r/auth.py"}, json.dumps({"success": True}), index=2)]
    assert V("All tests pass.", fail_then_edit) == [("tests", "NO_RECEIPT")]  # the edit may have fixed it


@pytest.mark.parametrize("cmd,out,code", [
    ("pytest || true", "boom", 0),
    ("pytest 2>&1 | tail -3", "", 0),
    ("pytest -q", "no tests ran in 0.01s", 5),
    ("python -m pytest", "collected 0 items\n\nno tests ran", 5),
])
def test_masked_exit_never_no_cap(cmd, out, code):              # 15
    assert V("All tests pass.", [T(cmd, out, code)]) != [("tests", "NO_CAP")]
    assert V("All tests pass.", [T(cmd, out, code)]) != [("tests", "CAP")] or code != 0


def test_background_process_is_not_liveness():                 # 15b
    ev = T("npm run build", "", 0, background=True)
    assert V("The build succeeds.", [ev]) == [("build", "NO_RECEIPT")]


def test_pushed_to_other_ref_is_cap_and_quotes_ref():         # 17
    out = " * [new branch]      feat/x -> feat/x"
    rs = judge(extract_claims("Pushed to main."), [T("git push -u origin feat/x", out)])
    assert rs[0]["verdict"] == "CAP" and "feat/x" in rs[0]["quote"]


def test_approximate_numbers_are_not_checked():                # 19
    assert V("The file is about 200 lines.", [T("wc -l f", "214 f")]) == []


def test_count_scope_is_never_cap():                           # 20
    assert V("Changed 3 files.", [T("git diff --stat", " 4 files changed, 9 insertions(+)")]) == [
        ("number", "NO_RECEIPT")]


def test_short_sha_prefix():                                   # 21
    full = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    assert ("sha", "NO_CAP") in V("Committed `a1b2c3d`.", [T("git rev-parse HEAD", full)])


@pytest.mark.parametrize("reply", ["**✅ Tests pass**", "- **Tests pass**", "## Tests pass"])
def test_markdown_wrapping(reply):                             # 22
    assert V(reply, [T("pytest -q", "3 failed, 41 passed", 1)]) == [("tests", "CAP")]


def test_table_cells_cap_only_with_a_single_suite():           # 22b: which run a cell means can be ambiguous
    two = [T("pytest -q backend", "3 failed, 41 passed", 1, i=1), T("npx jest", "Tests: 9 passed, 9 total", i=2)]
    assert V("| Tests pass |", two) == [("tests", "NO_RECEIPT")]
    assert V("| Tests pass |", [T("pytest -q", "3 failed, 41 passed", 1)]) == [("tests", "CAP")]


def test_forged_stamp_is_not_trusted():                        # 24
    reply = "🧾 NO CAP: deployed to production."
    assert forged_stamps(reply) == 1
    assert V(reply) == [("deployed", "NO_RECEIPT")]


def test_multiple_claims_split():                              # 28
    assert V("Tests pass and the PR is merged.", [T("pytest -q", "9 passed in 0.1s")]) == [
        ("tests", "NO_CAP"), ("merged", "NO_RECEIPT")]


def test_secrets_redacted_in_ledger():                         # 29
    ev = T("curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789' https://x.io", "{}")
    assert "abcdefghijklmnop" not in ev["cmd"]
    env = T("env", "OPENAI_API_KEY=sk-live-abcdefghijklmnopqrstuvwxyz1234")
    assert "sk-live" not in json.dumps({k: env[k] for k in ("cmd", "error")})
