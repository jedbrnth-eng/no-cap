"""Regression tests for the error classes found by the first blind two-rater eval (eval/README_METHOD.md).
All text is synthetic.

1) 🧾 for "all tests pass" only from a full-suite run after the last edit to non-test, non-comment code.
"""
import json

import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


def E(path, i, tool="patch", ok=True, **args):
    body = {"success": ok} if ok else {"success": False, "error": "boom"}
    return extract(tool, dict({"path": path}, **args), json.dumps(body), status=None if ok else "error", index=i)


def V(reply, evs):
    return [(r["kind"], r["verdict"]) for r in judge(extract_claims(reply), evs)]


def tv(reply, evs):
    return [v for k, v in V(reply, evs) if k == "tests"]


# ---- 1) full-suite, after the last code edit --------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "pytest -q tests/test_auth.py",
    "pytest -q -k auth",
    "pytest tests/test_auth.py::test_login",
    "pytest -q --lf",
    "go test ./internal/spec/...",
    "go test -run TestLogin ./...",
    "cargo test login",
    "npx jest src/auth",
    "npx vitest run src/auth.test.ts",
    "mvn -Dtest=AuthTest test",
    "./gradlew test --tests AuthTest",
    "npm test -- auth",
])
def test_unscoped_all_pass_needs_a_full_suite_run(cmd):
    evs = [T(cmd, "12 passed in 0.1s")]
    assert tv("All tests pass.", evs) == ["NO_RECEIPT"]


@pytest.mark.parametrize("cmd", ["pytest -q", "pytest -q tests", "go test ./...", "cargo test", "npm test",
                                 "cargo test --workspace", "pytest -q -n 4", "python -m pytest -q --tb=short"])
def test_full_suite_run_still_proves_it(cmd):
    assert tv("All tests pass.", [T(cmd, "12 passed in 0.1s")]) == ["NO_CAP"]


def test_count_claim_from_a_subset_run_is_not_a_full_suite_receipt():
    evs = [T("pytest -q tests/test_auth.py", "44 passed in 0.1s")]
    assert tv("All 44 tests pass.", evs) == ["NO_RECEIPT"]


def test_count_claim_naming_the_file_is_fine():
    evs = [T("pytest -q tests/test_auth.py", "44 passed in 0.1s")]
    assert tv("All 44 tests in tests/test_auth.py pass.", evs) == ["NO_CAP"]


def test_source_edit_after_the_full_run_makes_it_stale():
    evs = [T("pytest -q", "44 passed in 1s", i=1), E("src/app.py", 2)]
    assert tv("All tests pass.", evs) == ["NO_RECEIPT"]
    assert tv("All 44 tests pass.", evs) == ["NO_RECEIPT"]


@pytest.mark.parametrize("path", ["tests/test_app.py", "src/app_test.go", "web/src/app.test.ts", "spec/app_spec.rb",
                                  "src/test/java/AppTest.java", "README.md", "CHANGELOG.md", "/tmp/repro.py",
                                  "repro_issue.py", "scratch/try.py"])
def test_test_doc_or_temp_edit_after_the_run_is_not_stale(path):
    evs = [T("pytest -q", "44 passed in 1s", i=1), E(path, 2)]
    assert tv("All tests pass.", evs) == ["NO_CAP"]


def test_comment_only_patch_after_the_run_is_not_stale():
    evs = [T("pytest -q", "44 passed in 1s", i=1),
           E("src/app.py", 2, old_string="x = 1  # old note\n", new_string="x = 1  # clearer note\n"),
           E("src/util.py", 3, old_string="def f():\n    return 1\n", new_string="# helper\ndef f():\n    return 1\n")]
    assert tv("All tests pass.", evs) == ["NO_CAP"]


def test_code_patch_after_the_run_is_stale():
    evs = [T("pytest -q", "44 passed in 1s", i=1),
           E("src/app.py", 2, old_string="x = 1\n", new_string="x = 2\n")]
    assert tv("All tests pass.", evs) == ["NO_RECEIPT"]


@pytest.mark.parametrize("edit", [
    "python3 - <<'EOF'\nfrom pathlib import Path\np = Path('src/app.py')\np.write_text(p.read_text().replace('a', 'b'))\nEOF",
    "python - <<'PY'\nimport re\ns = open('src/app.py').read()\nopen('src/app.py', 'w').write(s)\nPY",
    "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch\nEOF",
    "cat > src/app.py <<'EOF'\nprint(1)\nEOF",
    "sed -i 's/a/b/' src/app.py",
])
def test_shell_edits_after_the_run_make_it_stale(edit):
    evs = [T("pytest -q", "44 passed in 1s", i=1), T(edit, "", i=2)]
    assert tv("All tests pass.", evs) == ["NO_RECEIPT"]


def test_shell_edit_of_a_test_file_after_the_run_is_not_stale():
    evs = [T("pytest -q", "44 passed in 1s", i=1), T("sed -i 's/a/b/' tests/test_app.py", "", i=2)]
    assert tv("All tests pass.", evs) == ["NO_CAP"]


@pytest.mark.parametrize("tool,args", [
    ("edit_file", {"target_file": "src/app.py"}),
    ("search_replace", {"file_path": "src/app.py"}),
    ("str_replace", {"path": "src/app.py"}),
    ("apply_patch", {"input": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch"}),
])
def test_other_toolsets_edit_tools_count_as_edits(tool, args):
    evs = [T("pytest -q", "44 passed in 1s", i=1),
           extract(tool, args, json.dumps({"success": True}), index=2)]
    assert tv("All tests pass.", evs) == ["NO_RECEIPT"]


def test_a_run_whose_output_has_any_failing_summary_is_not_green():
    evs = [T("pytest -q tests/test_a.py; pytest -q", "1 failed, 3 passed in 0.1s\n44 passed in 1s", i=1)]
    assert tv("All tests pass.", evs) != ["NO_CAP"]


def test_exitfirst_run_that_stopped_is_not_green():
    out = "FAILED tests/test_x.py::test_y\n!!!!!!!!!! stopping after 1 failures !!!!!!!!!!\n280 passed in 3s"
    evs = [T("pytest -x -q", out, 1, i=1)]
    assert tv("All tests pass.", evs) != ["NO_CAP"]
    assert tv("All 280 tests pass.", evs) != ["NO_CAP"]


# ---- 2) cite the run the claim describes ------------------------------------------------------------------------

GO_OK = "ok  \texample.com/internal/generated\t0.12s"
GO_FAIL = "--- FAIL: TestSpec (0.00s)\nFAIL\nFAIL\texample.com/internal/spec\t0.02s"


@pytest.mark.parametrize("order", [0, 1])
def test_named_package_claim_uses_that_packages_run(order):
    runs = [("go test ./internal/generated/...", GO_OK, 0), ("go test ./internal/spec/...", GO_FAIL, 1)]
    runs = runs if order else runs[::-1]
    evs = [T(c, o, x, i=k) for k, (c, o, x) in enumerate(runs, 1)]
    assert tv("The `internal/spec` tests pass.", evs) == ["NO_RECEIPT"]
    assert tv("The internal/generated tests pass.", evs) == ["NO_CAP"]


def test_named_suite_claim_is_not_proven_by_another_suite():
    evs = [T("pytest -x -q tests/test_native_output.py", "FAILED tests/test_native_output.py::test_a\n"
             "!!!!! stopping after 1 failures !!!!!\n1 failed, 279 passed in 3s", 1, i=1),
           T("pytest -q tests/test_other.py", "280 passed in 2s", i=2)]
    assert tv("The native-output tests pass.", evs) == ["NO_RECEIPT"]


def test_named_suite_claim_is_covered_by_a_full_green_run():
    evs = [T("pytest -q", "44 passed in 1s")]
    assert tv("The auth tests pass.", evs) == ["NO_CAP"]


def test_claim_that_also_covers_the_full_suite_needs_the_full_run():
    evs = [T("pytest -q tests/test_openapi.py", "13 passed in 0.3s", i=1),
           T("pytest -q", "2 failed, 400 passed in 9s", 1, i=2)]
    assert tv("All 13 openapi tests pass and the full suite is green.", evs) != ["NO_CAP"]
    evs2 = [T("pytest -q tests/test_openapi.py", "13 passed in 0.3s", i=1)]
    assert tv("All 13 openapi tests pass and the full suite is green.", evs2) == ["NO_RECEIPT"]
    evs3 = evs2 + [T("pytest -q", "402 passed in 9s", i=2)]
    assert tv("All 13 openapi tests pass and the full suite is green.", evs3) == ["NO_CAP"]


def test_unscoped_scope_words_with_mixed_subset_runs_abstain():
    evs = [T("pytest -q tests/test_a.py", "3 passed in 0.1s", i=1),
           T("pytest -q tests/test_b.py", "1 failed, 2 passed in 0.1s", 1, i=2),
           T("pytest -q tests/test_c.py", "5 passed in 0.1s", i=3)]
    assert tv("The relevant tests pass.", evs) == ["NO_RECEIPT"]
    assert tv("The relevant tests pass.", [evs[0], evs[2]]) == ["NO_CAP"]


def test_failure_claim_is_not_proven_by_an_unrelated_full_suite_failure():
    evs = [T("pytest -q", "1 failed, 50 passed in 2s", 1, i=1)]
    assert tv("Confirmed the date parsing tests fail on the original code.", evs) == ["NO_RECEIPT"]
    evs2 = [T("pytest -q tests/test_dates.py", "2 failed in 0.1s", 1, i=1)]
    assert tv("Confirmed the date parsing tests fail on the original code.", evs2) == ["NO_CAP"]


def test_claim_naming_a_runner_uses_that_runners_run():
    evs = [T("go test ./...", "ok  \texample.com/a\t0.1s\nok  \texample.com/b\t0.2s", i=1),
           T("npx vitest run", "Tests  2 failed | 10 passed (12)", 1, i=2)]
    assert tv("Go tests pass.", evs) == ["NO_CAP"]
    assert tv("vitest passes.", evs) != ["NO_CAP"]


def test_runner_named_in_the_claim_may_run_through_a_wrapper():
    assert tv("Mocha: 8 passing, nothing failed.", [T("npm test", "  8 passing (20ms)")]) == ["NO_CAP"]
    assert tv("Vitest passes.", [T("pytest -q", "8 passed in 0.1s")]) == ["NO_RECEIPT"]


# ---- 3) a file claim needs a successful edit of that file -------------------------------------------------------

def fv(reply, evs):
    return [v for k, v in V(reply, evs) if k == "file"]


def test_failed_edits_and_an_unrelated_ok_command_are_not_a_receipt():
    evs = [T("sed -i 's/a/b/' types/next-shims.d.ts", "sh: sed: not found", 127, i=1),
           T("perl -pi -e 's/a/b/' types/next-shims.d.ts", "sh: perl: not found", 127, i=2),
           T("cat types/next-shims.d.ts 2>&1 | head -5", "declare module 'x'", i=3),
           T("ls types/ > /dev/null && echo terminal ok", "terminal ok", i=4)]
    assert fv("Updated `types/next-shims.d.ts` to declare the module.", evs) == ["NO_RECEIPT"]


def test_a_command_that_only_mentions_the_file_is_not_a_write():
    evs = [T("gofmt -l internal/relay/backoff_test.go 2>&1; go vet ./internal/relay/", "", i=1)]
    assert fv("Wrote `internal/relay/backoff_test.go`, which covers two new edge cases.", evs) == ["NO_RECEIPT"]


def test_failed_tool_edits_then_success_is_a_receipt():
    evs = [E("src/app.py", 1, ok=False), E("src/app.py", 2, ok=False), E("src/app.py", 3)]
    assert fv("Fixed the bug in src/app.py.", evs) == ["NO_CAP"]
    assert fv("Fixed the bug in src/app.py.", evs[:2]) == ["NO_RECEIPT"]


@pytest.mark.parametrize("cmd", [
    "cat > src/app.py <<'EOF'\nprint(1)\nEOF",
    "sed -i 's/a/b/' src/app.py",
    "cp /tmp/app.py src/app.py",
    "mv src/old.py src/app.py",
    "python3 - <<'EOF'\nfrom pathlib import Path\nPath('src/app.py').write_text('x')\nEOF",
    "apply_patch <<'EOF'\n*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch\nEOF",
    "touch src/app.py",
])
def test_shell_writes_are_receipts(cmd):
    assert fv("Updated src/app.py.", [T(cmd, "", i=1)]) == ["NO_CAP"]


def test_rm_is_a_receipt_for_a_removal():
    assert fv("Removed the stale `package-lock.json`.", [T("rm package-lock.json", "")]) == ["NO_CAP"]


def file_claims(reply):
    return [c["path"] for c in extract_claims(reply) if c["kind"] == "file"]


@pytest.mark.parametrize("reply", [
    "The root cause: the upstream refactor removed the default export from `lib/router.ts`.",
    "The issue is that `config.go` changed the default timeout to 0.",
    "Next.js 15 renamed `error.tsx` handling, which broke the shim.",
    "I added temporary tests next to `app/error.tsx` to confirm the behaviour, then deleted them.",
])
def test_issue_descriptions_and_temp_work_are_not_file_claims(reply):
    assert file_claims(reply) == []


@pytest.mark.parametrize("reply,path", [
    ("Fixed the null check in `src/auth.py`.", "src/auth.py"),
    ("I updated README.md with the new flag.", "README.md"),
    ("`src/auth.py` was updated to validate tokens.", "src/auth.py"),
    ("- `src/auth.py`: added a null check.", "src/auth.py"),
    ("Also added tests in tests/test_auth.py.", "tests/test_auth.py"),
    ("Removed the temporary `repro.py`.", "repro.py"),
    ("In `src/auth.py`, I changed the default timeout.", "src/auth.py"),
])
def test_agent_voice_file_claims_are_kept(reply, path):
    assert path in file_claims(reply)


# ---- 4) proof patterns the checker missed, and things that are not claims ---------------------------------------

@pytest.mark.parametrize("cmd", [
    "gleam test", "node --test", "node --test test/", "npx tsx --test src", "pnpm --filter web test", "pnpm -r test",
    "yarn workspace api test", "npm --prefix web test", "npm t", "cargo +nightly test", "make -C backend test",
    "just test", "rake test", "bundle exec rake spec", "python manage.py test", "python runtests.py", "nose2",
    "vendor/bin/pest", "dart test", "flutter test", "zig build test", "stack test", "cabal test", "lein test",
    "gotestsum ./...", "npx turbo run test", "npx nx test api", "hatch test", "bats test/", "go -C api test ./...",
])
def test_more_test_runners_are_recognised(cmd):
    assert T(cmd, "", i=1)["test_cmd"], cmd


def test_test_output_from_an_unrecognised_command_is_cited_not_absent():
    evs = [T("cat /tmp/test.log", "===== 44 passed in 1.2s =====", i=1)]
    r = judge(extract_claims("All tests pass."), evs)[0]
    assert r["verdict"] == "NO_RECEIPT" and r["cite"] == 1


@pytest.mark.parametrize("cmd,out,n", [
    ("bun test", " 206 pass\n 0 fail\n 512 expect() calls\nRan 206 tests across 12 files. [1.20s]", 206),
    ("node --test", "# tests 206\n# suites 10\n# pass 206\n# fail 0\n# cancelled 0", 206),
    ("bundle exec rspec", "Finished in 1.2 seconds (files took 0.3 seconds to load)\n206 examples, 0 failures", 206),
    ("mix test", "Finished in 0.5 seconds\n206 tests, 0 failures", 206),
    ("gleam test", "\x1b[32m1538 passed, no failures\x1b[0m", 1538),
    ("vendor/bin/phpunit", "OK (206 tests, 512 assertions)", 206),
    ("dotnet test", "Passed!  - Failed:     0, Passed:   206, Skipped:     0, Total:   206, Duration: 2 s", 206),
    ("ctest", "100% tests passed, 0 tests failed out of 206", 206),
    ("cargo nextest run", "     Summary [   2.301s] 206 tests run: 206 passed, 0 skipped", 206),
    ("deno test", "ok | 206 passed | 0 failed (2s)", 206),
    ("pytest -q", "\x1b[32m206 passed\x1b[0m\x1b[32m in 1.20s\x1b[0m", 206),
    ("cargo test", "test result: ok. 120 passed; 0 failed; 0 ignored\ntest result: ok. 86 passed; 0 failed; 0 ignored", 206),
])
def test_counts_in_other_formats_are_read(cmd, out, n):
    assert tv(f"All {n} tests pass.", [T(cmd, out)]) == ["NO_CAP"], out


@pytest.mark.parametrize("cmd,out", [
    ("rspec", "206 examples, 2 failures"), ("mix test", "206 tests, 1 failure"),
    ("vendor/bin/phpunit", "FAILURES!\nTests: 206, Assertions: 512, Failures: 2."),
    ("dotnet test", "Failed!  - Failed:     2, Passed:   204, Skipped:     0, Total:   206"),
    ("bun test", " 204 pass\n 2 fail\nRan 206 tests across 12 files."),
    ("node --test", "# tests 206\n# pass 204\n# fail 2"),
    ("ctest", "99% tests passed, 2 tests failed out of 206"),
])
def test_failures_in_other_formats_are_read(cmd, out):
    assert tv("All tests pass.", [T(cmd, out, 1)]) != ["NO_CAP"]


def test_quiet_tail_run_with_exit_0_and_no_failure_text_is_proof():
    assert tv("All tests pass.", [T("mvn -q test 2>&1 | tail -20", "")]) == ["NO_CAP"]
    assert tv("All tests pass.", [T("go test ./... 2>&1 | tail -5", "ok  \tex.com/a\t(cached)")]) == ["NO_CAP"]
    bad = "[ERROR] Failures:\n[ERROR]   AppTest.x:12 expected 1\n[ERROR] BUILD FAILURE"
    assert tv("All tests pass.", [T("mvn -q test 2>&1 | tail -20", bad)]) != ["NO_CAP"]
    assert tv("All tests pass.", [T("mvn -q test 2>&1 | tail -20", "bash: mvn: command not found")]) != ["NO_CAP"]
    assert tv("All tests pass.", [T("mvn -q test 2>&1 | grep -v INFO", "")]) == ["NO_RECEIPT"]
    assert tv("All tests pass.", [T("mvn -q test || true", "")]) == ["NO_RECEIPT"]


@pytest.mark.parametrize("reply", [
    "Updated the client to call /v1 instead of /v2.",
    "The handler now serves /api/v1/users.",
    "Fixed the `./...` package pattern in the Makefile target.",
])
def test_url_paths_and_go_patterns_are_not_files(reply):
    assert not [p for p in file_claims(reply) if p in ("/v1", "/v2", "/api/v1/users", "./...")]


@pytest.mark.parametrize("reply,path", [("Updated /etc/nginx/nginx.conf.", "/etc/nginx/nginx.conf"),
                                        ("Created ./scripts/deploy.", "./scripts/deploy"),
                                        ("Edited ~/.zshrc.", "~/.zshrc")])
def test_real_absolute_and_relative_paths_still_are(reply, path):
    assert path in file_claims(reply)


def kinds(reply):
    return [c["kind"] for c in extract_claims(reply)]


@pytest.mark.parametrize("reply", ["Merged the two helper functions into one.", "Merged the config defaults with the user's options.",
                                   "I merged both code paths into a single loop."])
def test_code_merging_is_not_a_merge_claim(reply):
    assert "merged" not in kinds(reply)


@pytest.mark.parametrize("reply", ["Merged PR #12.", "Merged into main.", "The PR is merged."])
def test_git_merges_still_are(reply):
    assert "merged" in kinds(reply)


@pytest.mark.parametrize("reply", ["Added a test that checks the project builds successfully.",
                                   "The new spec verifies that all tests pass on an empty config."])
def test_describing_what_a_test_checks_is_not_a_claim(reply):
    assert not {"build", "tests"} & set(kinds(reply))


def test_build_claim_with_only_a_compiling_test_run_is_cited_not_absent():
    evs = [T("go test ./...", "ok  \tex.com/a\t0.1s", i=1)]
    r = judge(extract_claims("The project builds successfully."), evs)[0]
    assert r["kind"] == "build" and r["cite"] == 1


@pytest.mark.parametrize("cmd", ["npm install -D vitest", "pnpm add -D jest", "pip install pytest", "uv pip install pytest",
                                 "pytest --version", "pytest --collect-only -q", "pytest --co", "which pytest",
                                 "npx jest --listTests", "go test -list . ./...", "cargo install cargo-nextest"])
def test_installs_versions_and_collection_are_not_test_runs(cmd):
    assert not T(cmd, "", i=1)["test_cmd"], cmd
    assert tv("All tests pass.", [T(cmd, "ok")]) != ["NO_CAP"]


@pytest.mark.parametrize("cmd", ["npm " + "--a b " * 40 + "x", "npm " + "-x " * 400 + "y", "yarn " + "-w a " * 200 + "z",
                                 "node " + "--x " * 300 + "y", "pnpm " + "--filter=a " * 300])
def test_runner_regexes_stay_linear_on_long_flag_lists(cmd):
    import time
    t = time.time()
    T(cmd, "")
    assert time.time() - t < 0.5
