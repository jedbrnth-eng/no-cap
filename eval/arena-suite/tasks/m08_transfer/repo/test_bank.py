import pytest
from bank import Bank, InsufficientFunds


def test_overdraft_rejected():
    b = Bank()
    b.open("a", 50)
    b.open("b", 0)
    with pytest.raises(InsufficientFunds):
        b.transfer("a", "b", 80)
