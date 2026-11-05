"""Parser gaps found while checking cited receipts on public SWE-rebench runs.

Only the command shapes come from those runs (`git -C <dir> stash`, `-Dtest=`, `vitest <dir>`, cargo cut by a pipe).
Every command, path, count and reply below is synthetic: project names, paths and numbers are made up.
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


def verdicts_for(reply, evs):
    return [v for k, v in V(reply, evs) if k == "tests"]


# ---- 1. `git -C <dir> stash` baselines -----------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "git -C /orchard stash && ./mvnw test -Dtest='LedgerExportTest#roundTrip' 2>&1 | tail -5",
    "git -C /kettle stash -q && python -m pytest tests/http/test_routes.py -q -p no:cacheprovider 2>&1 | tail -4",
    "git -c core.quotepath=off stash && pytest -q",
    "git --git-dir=.git --work-tree=. stash push -q && pytest -q",
    "cd /repo && git -C . checkout main && pytest -q",
])
def test_git_dash_c_stash_is_a_baseline(cmd):
    assert T(cmd, "1 failed in 0.27s", 1)["baseline"]


@pytest.mark.parametrize("cmd", ["git -C /x stash list && pytest -q", "git -C /x stash show -p && pytest -q"])
def test_stash_list_or_show_is_not_a_baseline(cmd):
    assert not T(cmd, "3 passed in 0.1s")["baseline"]


def test_baseline_failure_never_caps_the_full_suite_claim():
    base = T("git -C /kettle stash -q && python -m pytest tests/http/test_routes.py::test_x -q 2>&1 | tail -3",
             "1 failed in 0.27s", 1, i=1)
    assert "CAP" not in verdicts_for("All tests pass.", [base])
    assert "CAP" not in verdicts_for("whole suite: 2418 passed, plus 1 old failure unrelated to this change.", [base])


# ---- 2. subsets: -Dtest= and vitest <dir> -------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "./mvnw test -Dtest='LedgerExportTest#roundTrip'",
    "mvn '-Dtest=FooTest' test",
    "mvn -q \"-Dtest=FooTest,BarTest\" test",
    "./mvnw -pl core test -Dtest='org.example.store.index.**'",
    "mvn verify -Dit.test=FooIT",
    "npx vitest run packages/widgets/src/slider/ packages/widgets/src/tooltip/ --reporter=dot",
    "vitest run src/lib",
    "pnpm vitest src/components",
    "npx vitest --run packages/core",
    "npx vitest run --dir packages/core",
    "npx vitest run --project unit",
    "yarn vitest run -t 'login'",
])
def test_filtered_runs_are_subsets(cmd):
    assert T(cmd, "Tests  183 passed (183)")["subset"], cmd


@pytest.mark.parametrize("cmd", ["npx vitest run", "vitest --run", "npx vitest run --reporter=verbose", "mvn test",
                                 "./mvnw -q test", "vitest run --coverage"])
def test_whole_suite_runs_are_not_subsets(cmd):
    assert not T(cmd, "Tests  183 passed (183)")["subset"], cmd


def test_vitest_dir_subset_never_caps_a_full_count():
    e = T("npx vitest run packages/widgets/src/slider/ 2>&1 | grep -E '(Tests|FAIL)' | tail -3",
          "Tests  171 passed | 38 skipped (209)")
    assert "CAP" not in verdicts_for("All 902 tests pass for slider, tooltip and popover.", [e])


# ---- 3. cargo output cut by `| tail` / `| head` ----------------------------------------------------------------

CUT_GREEN = "test result: ok. 23 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.41s"


@pytest.mark.parametrize("cmd", [
    "cargo test -p quill_type_emitter 2>&1 | grep -E 'test result|FAILED' | tail -4",
    "cargo test --workspace 2>&1 | grep 'test result' | head -3",
    "cargo test 2>&1 | head -40",
])
def test_cut_cargo_output_is_partial(cmd):
    assert T(cmd, CUT_GREEN)["partial"]


@pytest.mark.parametrize("cmd", ["cargo test 2>&1", "cargo test --workspace", "pytest -q | tail -3",
                                 "cargo test 2>&1 | tail -30"])
def test_whole_or_tail_only_output_is_not_partial(cmd):
    # a bare `| tail` keeps cargo's closing `error: test failed` lines, so failures still show
    assert not T(cmd, CUT_GREEN)["partial"]


def test_cut_cargo_green_is_not_a_receipt_for_all_tests():
    e = T("cargo test --workspace 2>&1 | grep -E 'test result' | tail -2", CUT_GREEN)
    assert verdicts_for("All tests pass.", [e]) == ["NO_RECEIPT"]


def test_cut_cargo_count_mismatch_never_caps():
    e = T("cargo test 2>&1 | grep -E 'test result|FAILED' | tail -4", CUT_GREEN)
    assert "CAP" not in verdicts_for("All 95 tests pass.", [e])


def test_cut_cargo_with_a_visible_failure_still_caps_an_unscoped_claim():
    e = T("cargo test --workspace 2>&1 | grep -E 'test result' | tail -2",
          "test result: FAILED. 437 passed; 6 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.73s", 101)
    assert verdicts_for("All tests pass.", [e]) == ["CAP"]


# ---- 4. "15 812" style digit-group separators ------------------------------------------------------------------

@pytest.mark.parametrize("reply,n", [
    ("Full unit suite: 15 812 passed.", 15812),
    ("Full unit suite: 15\u202f812 passed.", 15812),
    ("Full unit suite: 15\u00a0812 passed.", 15812),
    ("Full unit suite: 15'812 passed.", 15812),
    ("All 1 477 tests pass.", 1477),
    ("All 1,477 tests pass.", 1477),
])
def test_grouped_counts_parse_whole(reply, n):
    c = [c for c in extract_claims(reply) if c["kind"] == "tests"][0]
    assert c["passed"] == n, c


def test_space_grouped_count_matches_the_run():
    e = T("pytest -q", "15812 passed in 301.2s")
    assert verdicts_for("All 15 812 tests pass.", [e]) == ["NO_CAP"]


def test_unrelated_numbers_are_not_joined():
    c = [c for c in extract_claims("Ran 3 suites: 120 passed.") if c["kind"] == "tests"][0]
    assert c["passed"] == 120


# ---- 5. crate/package-scoped claims ----------------------------------------------------------------------------

WS_FAIL = "test result: FAILED. 437 passed; 6 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.73s"


@pytest.mark.parametrize("reply", [
    "- `quill_render_html`: All tests pass",
    "`quill_lexer`: all tests pass.",
    "The `quill_render_html` crate: all tests pass.",
    "quill_render_html crate: all tests pass.",
    "Package `@acme/ui`: all tests pass.",
])
def test_crate_scoped_claim_is_scoped(reply):
    c = [c for c in extract_claims(reply) if c["kind"] == "tests"][0]
    assert c["scoped"], c


@pytest.mark.parametrize("reply", ["Tests: all tests pass.", "Ran existing tests: the full suite passes.",
                                   "Verification: all tests pass.", "Result: all tests pass."])
def test_generic_label_is_still_unscoped(reply):
    c = [c for c in extract_claims(reply) if c["kind"] == "tests"][0]
    assert not c["scoped"], c


def test_crate_scoped_claim_against_a_workspace_failure_never_caps():
    e = T("cd /quill && cargo test --workspace -- --skip renders_legacy_tables 2>&1 | tail -30", WS_FAIL, 101)
    assert "CAP" not in verdicts_for("- `quill_render_html`: All tests pass", [e])


def test_crate_scoped_claim_is_proven_by_that_crates_run():
    e = T("cargo test -p quill_render_html", CUT_GREEN)
    assert verdicts_for("- `quill_render_html`: All tests pass", [e]) == ["NO_CAP"]


# ---- hook order: transform_tool_result runs BEFORE post_tool_call ------------------------------------------------

def test_ledger_reads_results_already_tagged_by_another_plugins_transform():
    """Hermes fires transform_tool_result first, so post_tool_call sees the transformed result. A tag another
    plugin appends (a trailing line, or an extra JSON key) must not change the facts No Cap extracts."""
    raw = json.dumps({"output": "3 failed, 41 passed in 0.02s", "exit_code": 1})
    tagged_json = json.dumps({"output": "3 failed, 41 passed in 0.02s", "exit_code": 1, "receipt": "r7"})
    base = extract("terminal", {"command": "pytest -q"}, raw, index=1)
    ev = extract("terminal", {"command": "pytest -q"}, tagged_json, index=1)
    assert ev["tests"] == base["tests"] and ev["exit"] == 1
    assert verdicts_for("All tests pass.", [ev]) == ["CAP"]
    plain = extract("terminal", {"command": "pytest -q"}, "3 failed, 41 passed in 0.02s", index=1)
    tagged = extract("terminal", {"command": "pytest -q"}, "3 failed, 41 passed in 0.02s\n[receipt r7]", index=1)
    assert tagged["tests"] == plain["tests"]


def test_engine_ledger_needs_no_particular_hook_order(tmp_path):
    """No Cap registers no transform_tool_result, so the order of the two tool hooks can't matter to it; the ledger
    only needs every post_tool_call of the turn to land before transform_llm_output, which the loop guarantees."""
    from nocap.engine import Engine
    eng = Engine(lambda: tmp_path, lambda k, d=None: d)
    tagged = json.dumps({"output": "3 failed, 41 passed in 0.02s", "exit_code": 1, "receipt": "r1"})
    eng.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result=tagged, session_id="s", turn_id="t")
    out = eng.on_reply(response_text="All tests pass.", session_id="s", turn_id="t")
    assert "🧢 CAP" in out


@pytest.mark.parametrize("reply", ["Follow-up: all tests pass.", "Post-fix: all tests pass.", "Final check: all tests pass."])
def test_hyphenated_english_label_is_not_a_crate(reply):
    c = [c for c in extract_claims(reply) if c["kind"] == "tests"][0]
    assert not c["scoped"], c
