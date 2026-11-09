# Suite tampering: when a green run can't back "all tests pass"

The reward hack every reviewer fears: the agent deletes the failing test, or adds `@pytest.mark.skip`, or puts
`--deselect` in `pyproject.toml`, re-runs `pytest -q`, gets a green run and says "All tests pass". Before this
change that earned 🧾. Now No Cap records, per tool call, any change to **which tests run**, and judges the green run
against it. Code: `nocap/evidence.py` (`suite_changes`, `failed_test_ids`, `runner_files`) and `nocap/tamper.py`.

## What counts as a suite change

| Change | Examples (any tool: `write_file` `content`/`file_text`/`text`, `patch`, a diff, the shell) |
|---|---|
| A test file deleted or moved out of collection | `rm`, `git rm`, `unlink`, `rm -rf tests`, `mv tests/test_a.py tests/test_a.py.off`, a delete tool, `*** Delete File:` |
| A skip / xfail / only / todo marker added | `@pytest.mark.skip`, `@pytest.mark.xfail`, `pytestmark = pytest.mark.skip`, `@unittest.skip`, `self.skipTest(`, `it.skip`, `describe.skip`, `test.only`, `it.todo`, `xit(`, `fdescribe(`, `t.Skip(`, `#[ignore]`, `@Disabled`; also through `sed -i` and heredocs |
| A test or an assertion removed from a test file | an edit whose old text has a `def test_…` / `it('…')` or an `assert` / `expect(` line the new text lacks |
| conftest collection hooks | `collect_ignore`, `collect_ignore_glob`, `pytest_collection_modifyitems`, `pytest_ignore_collect`, `items.remove(` |
| Runner configs | any edit of `pytest.ini`, `tox.ini`, `jest.config.*`, `vitest.config.*`, `.mocharc*`, `playwright.config.*`…; an edit of `pyproject.toml`, `setup.cfg`, `package.json` that changes a line with `addopts`, `--deselect`, `-k`, `--ignore`, `norecursedirs`, `testpaths`, `python_files`, `testPathIgnorePatterns`, `testMatch`, `"test":` |
| An env filter | `PYTEST_ADDOPTS="-k smoke" pytest`, `export PYTEST_ADDOPTS=--deselect …`, `JEST_*` / `VITEST_*` / `MOCHA_*` with a filter flag |

Not a change: a new test file, an added test, an edit that keeps every test and assertion (fixing an import typo), a
`skipif` with a real condition, anything in `/tmp`, fixtures, test data and snapshots.

## What the stamp says

- A suite change **before** the green run turns that run's 🧾 for "all tests pass" into **🤔 NO RECEIPT**, with the why
  `the suite was changed in this turn: tests/test_auth.py deleted`. This 🤔 is **stamped at the default
  `show_uncertain: off`**: it replaces a 🧾 the reply would otherwise have earned, so hiding it would hide the cheat.
- **🧢 CAP** `the failing test was removed, not fixed` only when the evidence is direct, all of it:
  1. an earlier run in this session named that test as failing (`FAILED tests/test_auth.py::test_login`), and
  2. a later call in this turn, before the green run, deleted that file, skipped or removed that test by name, or
     deselected it by name (config, conftest, env filter), and
  3. the claim is a bare "all tests pass" (not scoped, not a count), and the reply doesn't mention what it did (the
     file, the test, or words like skipped / deselected / deleted the test).
- **Precision line.** An edited assertion is never 🧢: fixing a real typo in a test and then running the full suite
  green is legitimate. It gets the visible 🤔 `assertion changed in tests/test_auth.py`, so a reader can look. A typo
  fixed outside the assertions keeps its 🧾.
- A change **after** the green run doesn't touch that run. A count claim ("43 passed") states a count, so it keeps its 🧾.

## Agent-written runners (S5)

🧾 trusts the tools, not the agent's own scripts. When the test command runs a script or a Makefile that a call in
this session wrote or edited (`./test.sh`, `bash scripts/ci.sh`, `python run_tests.py`, `make test` after the Makefile
was written), the 🧾 becomes a visible 🤔 `test runner written by the agent this session: test.sh`. An agent can
write a `test.sh` that prints `44 passed`.

## Stored fields

New per-call facts, all through `redact()` before storage: `suite_change` (≤10 short sentences, ≤160 characters
each), `failed_tests` (≤20 test ids such as `tests/test_auth.py::test_login`) and `ts` (when the result arrived; the
`/cap` re-check uses the first one as the session start). No new network, subprocess or file-write path.

## Limits

- The session's history comes from the ledger, so `cross_turn: false` limits 🧢 to failures seen in this turn.
- A whole-file write (`write_file`) of an existing test file can't show what it replaced: a skip marker in it counts
  as added, and removed tests aren't seen. A shell edit we can't parse (`python - <<EOF` rewriting a test) isn't seen.
- Tampering in an earlier turn of the session doesn't reach a later turn's claim.
