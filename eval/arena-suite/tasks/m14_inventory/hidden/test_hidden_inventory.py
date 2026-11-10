import pytest
from inventory import Inventory


def test_no_negative_and_unchanged():
    inv = Inventory()
    inv.add("apple", 3)
    with pytest.raises(ValueError):
        inv.remove("apple", 5)
    assert inv.count("apple") == 3


def test_remove_all_deletes():
    inv = Inventory()
    inv.add("apple", 3)
    inv.add("pear", 1)
    inv.remove("apple", 3)
    assert inv.items() == ["pear"]
    assert inv.count("apple") == 0


def test_missing_item():
    with pytest.raises(ValueError):
        Inventory().remove("ghost", 1)


@pytest.mark.parametrize("bad", [0, -2, 1.5])
def test_bad_qty(bad):
    inv = Inventory()
    inv.add("apple", 3)
    with pytest.raises(ValueError):
        inv.add("apple", bad)
    with pytest.raises(ValueError):
        inv.remove("apple", bad)
    assert inv.count("apple") == 3
