import pytest
from calc import evaluate


@pytest.mark.parametrize("expr,val", [("2+3*4", 14), ("10-3-2", 5), ("8/4/2", 1.0), ("(2+3)*4", 20),
                                      (" 7 ", 7), ("2*(3+(4-1))*2", 24), ("1+2*3-4/2", 5)])
def test_eval(expr, val):
    assert evaluate(expr) == val


def test_no_eval(monkeypatch):
    import builtins
    def boom(*a, **k):
        raise AssertionError("eval used")
    monkeypatch.setattr(builtins, "eval", boom)
    assert evaluate("1+1") == 2
