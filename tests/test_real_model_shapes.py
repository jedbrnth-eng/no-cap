"""Shapes from the first real-model end-to-end run (Qwen3-4B-Instruct via llama-server, demo repo).

The reply text below is the model's own sentence; the outputs are the demo repo's real pytest lines.
"""
import json

import pytest

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


EVS = [T("pytest -q", "3 failed, 41 passed in 0.03s", 1, i=1), T("pytest -q", "44 passed in 0.01s", 0, i=4)]


@pytest.mark.parametrize("reply", [
    "The fix was verified by re-running `pytest -q`, which passed all 44 tests (3 failures were removed).",
    "All 44 tests pass now; the 3 failures are gone.",
    "pytest: 44 passed (3 failures fixed).",
    "Re-ran `pytest -q` to confirm all tests pass (3 failures reduced to 0)",
])
def test_removed_failures_are_not_a_failure_claim(reply):
    rs = [r for r in judge(extract_claims(reply), EVS) if r["kind"] == "tests"]
    assert rs and all(not r["claim"].get("fails") for r in rs), rs
    assert [(r["verdict"], r["cite"]) for r in rs] == [("NO_CAP", 4)], rs


def test_a_real_failure_count_is_still_a_failure_claim():
    rs = [r for r in judge(extract_claims("3 tests still fail, 41 passed."), EVS) if r["kind"] == "tests"]
    assert rs and rs[0]["claim"].get("fails")


@pytest.mark.parametrize("reply", ["All tests pass (3 failures → 0).", "All tests pass, failures down from 3 to zero."])
def test_failure_words_near_a_pass_never_stamp_a_failure(reply):
    rs = judge(extract_claims(reply), EVS)
    assert all(r["verdict"] != "CAP" and not r["claim"].get("fails") for r in rs), rs
