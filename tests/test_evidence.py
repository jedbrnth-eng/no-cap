import json

from nocap.evidence import extract


def term(cmd, output, exit_code=0):
    return extract("terminal", {"command": cmd}, json.dumps({"output": output, "exit_code": exit_code, "error": None}))


def test_pytest_summary_failed():
    ev = term("pytest -q", "....F\nFAILED tests/test_a.py::test_x\n3 failed, 41 passed in 0.52s", 1)
    t = ev["tests"][0]
    assert (t["passed"], t["failed"]) == (41, 3)
    assert ev["exit"] == 1 and ev["test_cmd"] is True


def test_pytest_banner_summary():
    ev = term("python -m pytest", "===== 44 passed, 2 skipped in 1.10s =====")
    t = ev["tests"][0]
    assert (t["passed"], t["failed"], t["skipped"]) == (44, 0, 2)


def test_jest_summary():
    ev = term("npx jest", "Tests:       1 failed, 5 passed, 6 total\nTime: 2s", 1)
    t = ev["tests"][0]
    assert (t["passed"], t["failed"]) == (5, 1)


def test_vitest_summary():
    ev = term("npx vitest run", " Tests  2 failed | 10 passed (12)", 1)
    t = ev["tests"][0]
    assert (t["passed"], t["failed"]) == (10, 2)


def test_go_test_summary():
    out = "--- FAIL: TestLogin (0.00s)\nFAIL\nFAIL\texample.com/auth\t0.01s\nok  \texample.com/db\t0.02s"
    ev = term("go test ./...", out, 1)
    assert ev["tests"][0]["failed"] >= 1


def test_cargo_summary():
    ev = term("cargo test", "test result: ok. 7 passed; 0 failed; 0 ignored")
    assert ev["tests"][0]["passed"] == 7


def test_unittest_summary():
    ev = term("python -m unittest", "Ran 9 tests in 0.01s\n\nFAILED (failures=2, errors=1)", 1)
    t = ev["tests"][0]
    assert (t["failed"], t["errors"], t["passed"]) == (2, 1, 6)


def test_mocha_summary():
    ev = term("npm test", "  8 passing (20ms)\n  1 failing", 1)
    t = ev["tests"][0]
    assert (t["passed"], t["failed"]) == (8, 1)


def test_git_push_success():
    out = "To github.com:o/r.git\n * [new branch]      feat-x -> feat-x\nbranch 'feat-x' set up to track 'origin/feat-x'."
    ev = term("git push -u origin feat-x", out)
    assert ev["git"]["push_ok"] is True
    assert "feat-x" in ev["git"]["push_refs"]


def test_git_push_rejected():
    out = " ! [rejected]        main -> main (fetch first)\nerror: failed to push some refs"
    ev = term("git push origin main", out, 1)
    assert ev["git"]["push_ok"] is False


def test_git_commit_sha():
    ev = term("git commit -m 'x'", "[main 3f2a9c1] x\n 1 file changed, 2 insertions(+)")
    assert ev["git"]["commit"] == "3f2a9c1"
    assert "3f2a9c1" in ev["shas"]


def test_gh_pr_merge():
    ev = term("gh pr merge 42 --squash", "✓ Squashed and merged pull request #42 (Fix login)")
    assert ev["git"]["merged_prs"] == [42]


def test_gh_pr_create_url():
    ev = term("gh pr create --fill", "https://github.com/o/r/pull/43")
    assert ev["git"]["opened_prs"] == [43]


def test_write_file_path():
    ev = extract("write_file", {"path": "/tmp/x/src/main.py", "content": "print(1)"},
                 json.dumps({"bytes_written": 8}))
    assert ev["paths_written"] == ["/tmp/x/src/main.py"]
    assert ev["ok"] is True


def test_write_file_error():
    ev = extract("write_file", {"path": "/root/x.py", "content": ""}, json.dumps({"error": "Permission denied"}),
                 status="error")
    assert ev["ok"] is False


def test_http_status_from_curl():
    ev = term("curl -sI https://example.com/app", "HTTP/2 404\ncontent-type: text/html")
    assert ev["http"] == [404]
    assert "https://example.com/app" in ev["urls"]


def test_numbers_are_collected():
    ev = term("grep -rl secret . | wc -l", "      17\n")
    assert "17" in ev["numbers"]


def test_non_json_result():
    ev = extract("mystery", {}, "plain text 5 passed in 0.1s")
    assert ev["tests"][0]["passed"] == 5


def test_huge_output_is_bounded_and_keeps_tail():
    big = "x" * 5_000_000 + "\n2 failed, 10 passed in 3.0s"
    ev = term("pytest", big, 1)
    assert ev["tests"][-1]["failed"] == 2


def test_command_secrets_are_redacted():
    ev = term("curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz123456' https://api.x.com", "{}")
    assert "sk-abcdef" not in ev["cmd"]


def test_args_digest_is_stable():
    a = extract("terminal", {"command": "ls", "x": 1}, "{}")
    b = extract("terminal", {"x": 1, "command": "ls"}, "{}")
    assert a["digest"] == b["digest"]
