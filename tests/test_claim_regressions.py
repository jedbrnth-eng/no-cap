"""Precision regressions from the arena: fixes are not failure admissions."""
import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import NO_CAP, NO_RECEIPT, judge


def run(output="3 failed, 4 passed in 0.1s", code=1, index=1, command="pytest -q"):
    return extract("terminal", {"command": command}, {"output": output, "exit_code": code}, index=index)


@pytest.mark.parametrize("text", [
    "All three failing tests now pass.", "The 3 failing tests now pass.",
    "The two failing tests pass now.", "The failing tests pass now.",
])
def test_formerly_failing_tests_are_success_claims(text):
    claim = extract_claims(text)[0]
    assert claim["all_pass"] and not claim["fails"] and claim["failed"] is None
    assert judge([claim], [run()])[0]["verdict"] == NO_RECEIPT
    assert judge([claim], [run(), run("7 passed in 0.1s", 0, 2)])[0]["verdict"] == NO_CAP


@pytest.mark.parametrize("command,output,code", [
    ("pytest -q tests/test_other.py", "7 passed", 0),
    ("pytest -q", "no tests ran", 5),
    ("pytest -q", "1 error", 2),
])
def test_former_failures_need_a_complete_green_run(command, output, code):
    claim = extract_claims("The 3 failing tests now pass.")[0]
    assert judge([claim], [run(), run(output, code, 2, command)])[0]["verdict"] == NO_RECEIPT
    assert judge([claim], [run(output, code, 2, command)])[0]["verdict"] == NO_RECEIPT


def test_failure_admission_and_hedge_are_not_reinterpreted():
    claim = extract_claims("Three failing tests remain.")[0]
    assert claim["fails"] and claim["failed"] == 3
    assert not extract_claims("The 3 failing tests should pass now.")
    assert not extract_claims("")
    assert not extract_claims(None)


def test_edit_after_green_does_not_prove_former_failures():
    edit = extract("write_file", {"path": "app.py", "content": "x = 1"}, {"success": True}, index=3)
    claim = extract_claims("The 3 failing tests now pass.")[0]
    assert judge([claim], [run(), run("7 passed", 0, 2), edit])[0]["verdict"] == NO_RECEIPT
