import pytest
from retry import retry


def test_call_count_and_reraise():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError(f"no {len(calls)}")

    with pytest.raises(RuntimeError, match="no 3"):
        retry(boom, attempts=3)
    assert len(calls) == 3


def test_eventual_success():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise OSError("flaky")
        return "ok"

    assert retry(flaky, attempts=3) == "ok"
    assert state["n"] == 2


def test_bad_attempts():
    with pytest.raises(ValueError):
        retry(lambda: 1, attempts=0)
