import pytest
from inventory import Inventory


def test_no_negative():
    inv = Inventory()
    inv.add("apple", 3)
    with pytest.raises(ValueError):
        inv.remove("apple", 5)
