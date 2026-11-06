"""A file target is full only with a complete, bounded inventory."""
import os

import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import NO_CAP, NO_RECEIPT, judge


def evidence(root, command):
    return extract("terminal", {"command": command, "workdir": str(root)},
                   {"output": "1 passed in 0.1s", "exit_code": 0}, index=1)


@pytest.mark.parametrize("path", ["test_x.py", "tests/test_x.py", "tests/x_test.py", "tests/x.test.js"])
def test_only_file_is_full(tmp_path, path):
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("")
    ev = evidence(tmp_path, ("npx jest " if path.endswith(".js") else "pytest -q ") + path)
    assert not ev["subset"]
    assert judge(extract_claims("All tests pass."), [ev])[0]["verdict"] == NO_CAP


def test_all_explicit_files_are_full(tmp_path):
    for name in ("test_x.py", "test_y.py"):
        (tmp_path / name).write_text("")
    assert not evidence(tmp_path, "pytest test_x.py test_y.py -q")["subset"]


@pytest.mark.parametrize("command", [
    "pytest test_x.py -k one", "pytest test_x.py::test_one", "pytest test_x.py -m smoke",
    "pytest test_x.py --lf", "pytest test_x.py --ignore test_y.py", "pytest test_x.py missing.py",
])
def test_filters_and_unknown_targets_stay_partial(tmp_path, command):
    (tmp_path / "test_x.py").write_text("")
    assert evidence(tmp_path, command)["subset"]


def test_another_file_blocks_full_run(tmp_path):
    for path in ("test_x.py", "test_y.py"):
        (tmp_path / path).write_text("")
    ev = evidence(tmp_path, "pytest test_x.py")
    assert ev["subset"]
    assert judge(extract_claims("All tests pass."), [ev])[0]["verdict"] == NO_RECEIPT


def test_empty_missing_and_symlink_inventory_abstains(tmp_path):
    assert evidence(tmp_path, "pytest test_x.py")["subset"]
    assert evidence(tmp_path / "missing", "pytest test_x.py")["subset"]
    (tmp_path / "test_x.py").symlink_to(tmp_path / "missing.py")
    assert evidence(tmp_path, "pytest test_x.py")["subset"]


def test_bounded_inventory_abstains(tmp_path):
    (tmp_path / "test_x.py").write_text("")
    deep = tmp_path / "a/b/c/d/e"
    deep.mkdir(parents=True)
    (deep / "test_y.py").write_text("")
    assert evidence(tmp_path, "pytest test_x.py")["subset"]


def test_entry_limit_abstains_without_large_fixture(tmp_path, monkeypatch):
    (tmp_path / "test_x.py").write_text("")
    real = os.scandir
    class Repeated:
        def __enter__(self):
            self.scan = real(tmp_path)
            return iter(list(self.scan) * 2001)
        def __exit__(self, *args):
            self.scan.close()
    monkeypatch.setattr(os, "scandir", lambda _: Repeated())
    assert evidence(tmp_path, "pytest test_x.py")["subset"]


def test_permission_failure_abstains(tmp_path, monkeypatch):
    def denied(_):
        raise PermissionError("denied")
    monkeypatch.setattr(os, "scandir", denied)
    assert evidence(tmp_path, "pytest test_x.py")["subset"]


def test_cd_sets_inventory_root(tmp_path):
    (tmp_path / "test_x.py").write_text("")
    assert not evidence(tmp_path.parent, f"cd '{tmp_path}' && pytest test_x.py")["subset"]


def test_ledger_names_another_test_file(tmp_path):
    (tmp_path / "test_x.py").write_text("")
    seen = extract("read_file", {"path": "tests/test_y.py"}, {"content": ""}, index=1)
    ev = evidence(tmp_path, "pytest test_x.py")
    ev["i"] = 2
    assert not ev["subset"]  # disk alone is complete; the ledger adds contrary scope evidence
    assert judge(extract_claims("All tests pass."), [seen, ev])[0]["verdict"] == NO_RECEIPT


def test_file_targets_are_redacted_before_ledger_storage(tmp_path):
    from nocap.evidence import ledger_fact
    name = "test_password=fixture_only.py"
    (tmp_path / name).write_text("")
    ev = evidence(tmp_path, "pytest " + name)
    assert not ev["subset"]
    assert "fixture_only" not in str(ev["test_files"])
    assert "fixture_only" not in str(ledger_fact(ev)["test_files"])


def test_file_run_does_not_nudge_strict(tmp_path):
    from nocap.engine import Engine
    (tmp_path / "test_x.py").write_text("")
    engine = Engine(lambda: tmp_path / "store", lambda k, d=None: "strict" if k == "mode" else d)
    engine.on_tool(tool_name="terminal", args={"command": "pytest test_x.py", "workdir": str(tmp_path)},
                   result={"output": "1 passed", "exit_code": 0}, session_id="s", turn_id="t")
    assert engine.on_verify(session_id="s", final_response="All tests pass.") is None


@pytest.mark.parametrize("other", ["b.spec.js", "c.test.ts", "__tests__/d.js", "test_e.py"])
def test_other_runner_shapes_block_full_js_run(tmp_path, other):
    (tmp_path / "a.test.js").write_text("")
    (tmp_path / other).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / other).write_text("")
    assert evidence(tmp_path, "npx jest a.test.js")["subset"]


def test_mocha_file_run_stays_partial(tmp_path):
    (tmp_path / "a.test.js").write_text("")  # mocha's default spec is every file under test/, whatever the name
    assert evidence(tmp_path, "npx mocha a.test.js")["subset"]


@pytest.mark.parametrize("command", ["pytest test_x.py && cd other", "cd a && cd b && pytest test_x.py",
                                     "git -C other status && pytest test_x.py"])
def test_unknown_inventory_root_abstains(tmp_path, command):
    (tmp_path / "test_x.py").write_text("")
    for d in ("other", "a/b"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / d / "test_x.py").write_text("")
    assert evidence(tmp_path, command)["subset"]


def test_root_is_never_the_plugin_process_cwd(tmp_path, monkeypatch):
    (tmp_path / "test_x.py").write_text("")
    monkeypatch.chdir(tmp_path)  # the plugin's own cwd holds only test_x.py; the session's repo is unknown
    ev = extract("terminal", {"command": "pytest test_x.py"}, {"output": "1 passed", "exit_code": 0}, index=1)
    assert ev["subset"]
    assert extract("terminal", {"command": "pytest test_x.py", "workdir": "."}, {"output": "1 passed", "exit_code": 0},
                   index=1)["subset"]


def test_session_cwd_and_reported_cwd_place_the_run(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "test_x.py").write_text("")
    ok = {"output": "1 passed", "exit_code": 0}
    assert not extract("terminal", {"command": "pytest test_x.py"}, ok, index=1, cwd=str(tmp_path / "sub"))["subset"]
    # Hermes reports "cwd" only when the command changed directory: that is where the run happened
    moved = dict(ok, cwd=str(tmp_path / "sub"))
    assert not extract("terminal", {"command": "cd sub && pytest test_x.py", "workdir": str(tmp_path)}, moved,
                       index=1)["subset"]


def test_engine_passes_session_cwd(tmp_path):
    from nocap.engine import Engine
    (tmp_path / "test_x.py").write_text("")
    engine = Engine(lambda: tmp_path / "store", lambda k, d=None: "strict" if k == "mode" else d,
                    cwd=lambda: str(tmp_path))
    engine.on_tool(tool_name="terminal", args={"command": "pytest test_x.py"},
                   result={"output": "1 passed", "exit_code": 0}, session_id="s", turn_id="t")
    assert engine.on_verify(session_id="s", final_response="All tests pass.") is None


# ---- cross-family review (orca-flash) findings ----
def test_vitest_mts_files_block_full_run(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("a.test.ts", "b.test.mts"):
        (tmp_path / "src" / name).write_text("")
    assert evidence(tmp_path, "npx vitest run src/a.test.ts")["subset"]


@pytest.mark.parametrize("config,body", [("pytest.ini", "[pytest]\npython_files = *_tests.py\n"),
                                         ("pyproject.toml", "[tool.pytest.ini_options]\npython_files = ['check_*.py']\n"),
                                         ("jest.config.js", "module.exports = {testMatch: ['**/*.it.js']}\n")])
def test_runner_pattern_override_abstains(tmp_path, config, body):
    (tmp_path / config).write_text(body)
    (tmp_path / ("a.test.js" if config.startswith("jest") else "test_x.py")).write_text("")
    assert evidence(tmp_path, "npx jest a.test.js" if config.startswith("jest") else "pytest test_x.py")["subset"]


def test_plain_runner_config_still_counts(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts = '-q'\n")
    (tmp_path / "test_x.py").write_text("")
    assert not evidence(tmp_path, "pytest test_x.py")["subset"]


@pytest.mark.parametrize("marker", [".git", "pyproject.toml", None])
def test_run_inside_tests_dir_sees_the_rest_of_the_project(tmp_path, marker):
    if marker:
        (tmp_path / marker).mkdir() if marker == ".git" else (tmp_path / marker).write_text("")
    (tmp_path / "test_root.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("")
    assert evidence(tmp_path, "cd tests && pytest test_x.py")["subset"]
    assert evidence(tmp_path / "tests", "pytest test_x.py")["subset"]


def test_run_inside_tests_dir_counts_when_it_is_the_only_file(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("")
    ev = evidence(tmp_path / "tests", "pytest test_x.py")
    assert not ev["subset"] and ev["test_files"] == ["tests/test_x.py"]
