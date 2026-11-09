import pytest
from shop.money import add_tax, discount, split


@pytest.mark.parametrize("price,pct,out", [(10.05, 50, 5.03), (100, 25, 75.0), (0.05, 50, 0.03), (9.99, 10, 8.99)])
def test_discount(price, pct, out):
    assert discount(price, pct) == out


@pytest.mark.parametrize("price,rate,out", [(2.5, 5, 2.63), (100, 20, 120.0), (0.1, 50, 0.15), (19.99, 0, 19.99)])
def test_tax(price, rate, out):
    assert add_tax(price, rate) == out


def test_split():
    assert split(10, 3) == [3.34, 3.33, 3.33]
