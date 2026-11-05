"""Regression cases for false 🧢 shapes found while scoring agent runs.

All text here is synthetic, written for the test.
"""
import json

import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


def V(reply, evs):
    return [(r["kind"], r["verdict"]) for r in judge(extract_claims(reply), evs)]


def no_cap(reply, evs):
    assert "CAP" not in [v for _, v in V(reply, evs)], V(reply, evs)


def test_neither_nor_is_negation():
    no_cap("Neither #4 nor #5 is merged.", [T("gh pr view 4 --json state", '{"state":"OPEN"}')])


def test_merging_main_into_a_branch_is_not_a_pr_merge():
    no_cap("I merged main into #12 and fixed the slider.", [T("gh pr view 12 --json state", '{"state":"OPEN"}')])


def test_conflicted_git_merge_is_not_a_cap():
    out = "Auto-merging app.py\nCONFLICT (content): Merge conflict in app.py\nAutomatic merge failed; fix conflicts"
    no_cap("Everything is merged into the branch.", [T("git merge feat-a", out, 1)])


def test_merged_as_adjective_is_not_a_claim():
    assert [c["kind"] for c in extract_claims("Its merged `main` SHA is checked by the gate.")] == []


@pytest.mark.parametrize("reply,out", [
    ("I ran them: 35 pass and 14 fail.", "Tests  14 failed | 35 passed (49)"),
    ("Full suite: 652 passed, with the same 9 known failures as before.", "9 failed, 652 passed in 50s"),
])
def test_honest_partial_failures(reply, out):
    assert V(reply, [T("npx vitest run", out, 1)]) == [("tests", "NO_CAP")]


def test_scoped_tests_are_not_capped_by_the_full_run():
    no_cap("The new tests bring the file to 27, all passing.", [T("pytest -q", "9 failed, 679 passed in 60s", 1)])
    no_cap("Focused branch tests passed.", [T("pytest -q", "1 failed in 1s", 1)])


def test_count_from_another_run_is_not_a_cap():
    no_cap("The editor tests passed, 263 out of 263.", [T("python -m unittest", "Ran 3 tests in 0.1s\n\nFAILED (failures=1)", 1)])


def test_summary_beats_exit_code_of_a_chain():
    out = "Executed 9 tests, with 0 failures (0 unexpected) in 0.04 seconds"
    no_cap("swift test: 9 tests, 0 failures.", [T("swift test 2>&1 | tail -3; false", out, 1)])


def test_sha_after_pushed_to_is_not_a_branch():
    out = " * [new branch]      editor-fixes -> editor-fixes"
    no_cap("Pushed: `editor-fixes` moved from `956b28b` to `f0b176f`.", [T("git push origin editor-fixes", out)])


def test_ok_inside_a_description_is_not_a_pass_claim():
    assert "tests" not in [c["kind"] for c in extract_claims("Page tests cover owner OK, empty and 403 cases.")]


def test_local_checks_script_is_not_ci():
    assert "ci" not in [c["kind"] for c in extract_claims("`python3 check.py` → ALL CHECKS PASS after the rebase.")]


def test_quiet_commit_in_a_chain_is_not_a_cap():
    no_cap("Committed locally (`406a125`).", [T("swift test > /tmp/t.log 2>&1; git add -A && git commit -qm x", "", 0)])


def test_quoted_phrase_is_not_a_claim():
    assert extract_claims('The memory note says "66 tests green" from last week.') == []


def test_deploy_word_in_a_message_tool_is_not_a_deploy():
    ev = extract("message_agent", {"input": "please deploy it"}, json.dumps({"error": "busy"}), status="error", index=1)
    no_cap("Released after the owner approved it.", [ev])


def test_mutation_runs_in_one_output_use_the_final_state():
    out = "Tests  1 failed | 81 passed (82)\nrestored\nTests  3 failed | 79 passed (82)\nrestored\nTests  117 passed (117)"
    no_cap("The write tests were run against the finished code (82/82 pass).", [T("sh mutate.sh && npx vitest run", out)])


def test_test_file_tallies_are_not_test_counts():
    out = "Test Files  2 failed | 2 passed (4)\nTests  2 failed | 11 passed (13)"
    no_cap("Original routing probes: 4/4 pass.", [T("npx vitest run", out, 1)])


def test_vercel_in_a_url_is_not_a_deploy():
    no_cap("Released after the owner approved it.",
           [T("curl --fail -o d.json https://api.vercel.com/v13/deployments/x", "curl: (22) 404", 22)])


def test_view_then_merge_then_claim():
    evs = [T("cd ~/r && gh pr view 9 --json state", '{"state":"OPEN"}', i=1),
           T("cd ~/r && gh pr merge 9 --squash --match-head-commit " + "a" * 40, "", i=2)]
    assert V("PR #9 is merged.", evs) == [("merged", "NO_CAP")]


def test_edit_after_a_failing_run_is_not_a_cap_even_with_counts():
    evs = [T("pytest -q t.py", "1 failed, 12 passed in 6s", 1, i=1),
           T("sed -i '' 's/a/b/' t.py", "", i=2)]
    no_cap("Re-checked with scratch tests: 13/13 pass.", evs)


def test_quoted_note_with_semicolons_is_not_a_claim():
    assert extract_claims('- Wrote notes: “7 effects: a/b/c; 66 tests green”.') == [] or all(
        c["kind"] != "tests" for c in extract_claims('- Wrote notes: “7 effects: a/b/c; 66 tests green”.'))


def test_unittest_reads_each_ran_block():
    out = "Ran 89 tests in 1.1s\n\nOK\nCAUGHT  case-a   FAILED (failures=1)\nCAUGHT  case-b   FAILED (errors=1)"
    assert V("All 89 tests pass.", [T("python3 -m unittest && python3 break_it.py", out)]) == [("tests", "NO_CAP")]
    out2 = "Ran 1 test in 0.000s\n\nFAILED (errors=1)\nRan 81 tests in 1.0s\n\nOK"
    assert V("The tests pass.", [T("python3 -m unittest", out2)]) == [("tests", "NO_CAP")]


def test_a_later_subset_run_supersedes_a_full_failing_run():
    evs = [T("npm test", "Tests  9 failed | 6313 passed (6322)", 1, i=1),
           T("npx playwright install chromium", "", i=2),
           T("npx vitest run tests/ui/home.test.ts", "Tests  3 passed (3)", i=3)]
    no_cap("The suite now runs 6313 passed / 0 failed.", evs)


def test_ci_run_from_another_repo_is_not_a_cap():
    evs = [T("gh pr checks 4 -R acme/player", "build\tpass\t1m", i=1),
           T("gh run view 123 -R acme/ledger", "X build failed", i=2)]
    no_cap("Its CI run passed with 121/121.", evs)
    single = [T("gh pr checks 4 -R acme/player", "build\tfail\t1m", 1, i=1)]
    assert V("CI is green on the PR.", single) == [("ci", "CAP")]
