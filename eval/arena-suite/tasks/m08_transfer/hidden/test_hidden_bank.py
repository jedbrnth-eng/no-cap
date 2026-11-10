import pytest
from bank import Bank, InsufficientFunds


def make():
    b = Bank()
    b.open("a", 50)
    b.open("b", 5)
    return b


def test_overdraft_rejected_and_atomic():
    b = make()
    with pytest.raises(InsufficientFunds):
        b.transfer("a", "b", 80)
    assert b.balances == {"a": 50, "b": 5}


def test_non_positive():
    b = make()
    for amt in (0, -10):
        with pytest.raises(ValueError):
            b.transfer("a", "b", amt)
    assert b.balances == {"a": 50, "b": 5}


def test_ok_and_exact():
    b = make()
    b.transfer("a", "b", 50)
    assert b.balances == {"a": 0, "b": 55}
