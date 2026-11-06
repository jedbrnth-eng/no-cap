"""Honest failure reports must not consume strict-mode repair attempts."""
import pytest

from nocap.claims import extract_claims
from nocap.engine import Engine
from nocap.verdict import CAP, NO_CAP, judge
from nocap.evidence import extract


@pytest.mark.parametrize("text", [
    "However, the tests still fail because the original test cases expect exact matches.",
    "The original tests still fail.", "2 tests are still failing.",
    "The parser tests still fail.",
])
@pytest.mark.parametrize("output,code", [("2 failed, 8 passed", 1), ("10 passed", 0), ("", None)])
def test_admissions_never_nudge_even_when_unverified(tmp_path, text, output, code):
    engine = Engine(lambda: tmp_path, lambda k, d=None: "strict" if k == "mode" else d)
    if code is not None:
        engine.on_tool(tool_name="terminal", args={"command": "pytest -q"},
                       result={"output": output, "exit_code": code}, session_id="s", turn_id="t")
    assert engine.on_verify(session_id="s", final_response=text) is None
    claims = extract_claims(text)
    assert claims and claims[0]["fails"]
    evs = [] if code is None else [extract("terminal", {"command": "pytest -q"},
                                          {"output": output, "exit_code": code}, index=1)]
    assert all(r["verdict"] != CAP for r in judge(claims, evs))


def test_vague_failure_does_not_gain_unrelated_receipt():
    ev = extract("terminal", {"command": "pytest -q"}, {"output": "2 failed, 8 passed", "exit_code": 1}, index=1)
    rs = judge(extract_claims("The parser tests still fail."), [ev])
    assert rs and rs[0]["verdict"] != NO_CAP


def test_failure_admission_does_not_silence_unproven_success(tmp_path):
    engine = Engine(lambda: tmp_path, lambda k, d=None: "strict" if k == "mode" else d)
    assert engine.on_verify(session_id="s", final_response="The parser tests still fail. Pushed to main.")
    assert engine.on_verify(session_id="s", final_response="All tests pass.")
    assert engine.on_verify(session_id="s", final_response="The failing tests now pass.")
