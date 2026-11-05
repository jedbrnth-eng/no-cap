"""Footer lines quote the claim's own fragment, not the whole clause again for every claim in it."""
import json

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.render import footer, receipt_line
from nocap.verdict import judge


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


REPLY = "Fixed the login bug in auth.py. All tests pass ✅, pushed to main, and the deploy is live."
EVS = [T("pytest -q", "3 failed, 41 passed in 0.02s", 1, i=1),
       T("git push origin feat/login", "To ../origin.git\n * [new branch]      feat/login -> feat/login", 0, i=2)]


def receipts():
    return judge(extract_claims(REPLY), EVS)


def test_each_claim_in_a_shared_clause_gets_its_own_fragment():
    by_kind = {r["kind"]: r for r in receipts()}
    assert by_kind["tests"]["verdict"] == by_kind["pushed"]["verdict"] == "CAP"
    assert by_kind["tests"]["claim"]["frag"] == "All tests pass ✅"
    assert by_kind["pushed"]["claim"]["frag"] == "pushed to main"


def test_footer_does_not_repeat_the_clause():
    out = footer(receipts())
    assert "“All tests pass ✅”" in out and "“pushed to main”" in out
    assert "All tests pass ✅, pushed to main" not in out


def test_single_claim_clause_keeps_its_text():
    r = judge(extract_claims("All 44 tests pass."), [T("pytest -q", "44 passed in 0.1s")])[0]
    assert "“All 44 tests pass.”" in receipt_line(r)


def test_fragment_does_not_change_verdicts():
    plain = [(r["kind"], r["verdict"], r["cite"]) for r in receipts()]
    assert plain == [("tests", "CAP", 1), ("pushed", "CAP", 2), ("file", "NO_RECEIPT", None),
                     ("deployed", "NO_RECEIPT", None)] or sorted(plain, key=str) == sorted(
        [("tests", "CAP", 1), ("pushed", "CAP", 2), ("file", "NO_RECEIPT", None), ("deployed", "NO_RECEIPT", None)],
        key=str)


def test_steer_quotes_the_fragment(tmp_path):
    from nocap.engine import Engine
    out = Engine._steer([r for r in receipts() if r["verdict"] == "CAP"], [])
    assert "“pushed to main”" in out and "“All tests pass ✅”" in out


def test_irregular_verb_after_and_splits_the_fragment():
    cs = extract_claims("I fixed the reversed check in `auth.py` and re-ran pytest: 44 passed.")
    frags = {c["kind"]: c.get("frag") for c in cs}
    assert frags["file"] == "I fixed the reversed check in `auth.py`"
    assert frags["tests"] == "re-ran pytest: 44 passed."
