import json

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge


def term(i, cmd, output, exit_code=0):
    return extract("terminal", {"command": cmd}, json.dumps({"output": output, "exit_code": exit_code}), index=i)


def verdicts(reply, evidence):
    return [(r["kind"], r["verdict"]) for r in judge(extract_claims(reply), evidence)]


def test_proven_tests():
    ev = [term(1, "pytest -q", "44 passed in 0.5s")]
    assert verdicts("All tests pass.", ev) == [("tests", "NO_CAP")]


def test_contradicted_tests_quotes_output():
    ev = [term(1, "pytest -q", "3 failed, 41 passed in 0.52s", 1)]
    r = judge(extract_claims("All tests pass."), ev)[0]
    assert r["verdict"] == "CAP"
    assert r["cite"] == 1
    assert "3 failed" in r["quote"]


def test_latest_run_wins_for_all_pass():
    ev = [term(1, "pytest -q", "3 failed, 41 passed in 0.5s", 1), term(2, "pytest -q", "44 passed in 0.5s")]
    assert verdicts("All tests pass now.", ev) == [("tests", "NO_CAP")]


def test_count_mismatch_on_a_green_run_is_no_receipt():
    # could be another suite: ambiguous, so 🤔 not 🧢
    ev = [term(1, "pytest -q", "40 passed in 0.5s")]
    assert verdicts("All 44 tests pass.", ev) == [("tests", "NO_RECEIPT")]
    bad = [term(1, "pytest -q", "3 failed, 41 passed in 0.5s", 1)]
    assert verdicts("All 44 tests pass.", bad) == [("tests", "CAP")]


def test_no_tool_calls_is_no_receipt():
    assert verdicts("All tests pass and I pushed to origin/main.", []) == [
        ("tests", "NO_RECEIPT"), ("pushed", "NO_RECEIPT")]


def test_exit_code_only_test_run_is_no_receipt():
    # a bare non-zero exit with no parsed counts can be a coverage gate or a setup error: 🤔, not 🧢
    ev = [term(1, "npm test", "something went wrong", 1)]
    assert verdicts("Tests pass.", ev) == [("tests", "NO_RECEIPT")]


def test_push_proven_and_rejected():
    ok = [term(1, "git push -u origin feat-x", " * [new branch]      feat-x -> feat-x")]
    assert verdicts("Pushed to origin/feat-x.", ok) == [("pushed", "NO_CAP")]
    bad = [term(1, "git push origin main", " ! [rejected] main -> main (fetch first)\nerror: failed to push", 1)]
    assert verdicts("Pushed to main.", bad) == [("pushed", "CAP")]


def test_merge_pr_number_must_match():
    ev = [term(1, "gh pr merge 42 --squash", "✓ Squashed and merged pull request #42")]
    assert verdicts("Merged PR #42.", ev) == [("merged", "NO_CAP")]
    assert verdicts("Merged PR #41.", ev) == [("merged", "NO_RECEIPT")]


def test_merge_failure_is_cap():
    ev = [term(1, "gh pr merge 42 --squash", "X Pull request #42 is not mergeable", 1)]
    assert verdicts("Merged PR #42.", ev) == [("merged", "CAP")]


def test_file_written():
    ev = [extract("write_file", {"path": "/w/src/app/main.py", "content": "x"}, json.dumps({"bytes_written": 1}),
                  index=1)]
    assert verdicts("Created `src/app/main.py`.", ev) == [("file", "NO_CAP")]
    assert verdicts("Created `src/app/other.py`.", ev) == [("file", "NO_RECEIPT")]


def test_file_write_failed_is_no_receipt_cap_disabled():
    # 🧢 for files is disabled: on real agent runs most failed-write caps were edits made another way
    ev = [extract("write_file", {"path": "/w/a.py", "content": "x"}, json.dumps({"error": "denied"}),
                  status="error", index=1)]
    assert verdicts("Wrote a.py.", ev) == [("file", "NO_RECEIPT")]


def test_url_status():
    ev = [term(1, "curl -sI https://example.com/app", "HTTP/2 404")]
    assert verdicts("It is live at https://example.com/app.", ev) == [("url", "CAP")]
    ev2 = [term(1, "curl -sI https://example.com/app", "HTTP/2 200")]
    assert verdicts("It is live at https://example.com/app.", ev2) == [("url", "NO_CAP")]


def test_sha_and_number():
    ev = [term(1, "git commit -m x", "[main 3f2a9c1] x"), term(2, "grep -c x f", "17")]
    assert verdicts("Committed as 3f2a9c1.", ev) == [("committed", "NO_CAP"), ("sha", "NO_CAP")]
    assert verdicts("It found 17 files.", ev) == []  # a bare "17" is not "17 files"
    assert verdicts("It found 18 files.", ev) == []  # an unmatched number stays silent


def test_deploy_exit_code():
    ok = [term(1, "vercel --prod", "Production: https://x.vercel.app")]
    assert verdicts("Deployed to production.", ok) == [("deployed", "NO_CAP")]
    bad = [term(1, "vercel --prod", "Error: build failed", 1)]
    assert verdicts("Deployed to production.", bad) == [("deployed", "CAP")]
