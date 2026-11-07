import time
import pytest
from shop.money import add_tax, discount, split

SLOW = 2.5


@pytest.mark.parametrize("price,rate,out", [(2.5, 5, 2.63), (100, 20, 120.0), (0.1, 50, 0.15),
                                            (19.99, 0, 19.99)])
def test_tax(price, rate, out):
    time.sleep(SLOW)
    assert add_tax(price, rate) == out


@pytest.mark.parametrize("total,n,out", [(10, 3, [3.34, 3.33, 3.33]), (1, 4, [0.25] * 4)])
def test_split(total, n, out):
    time.sleep(SLOW)
    assert split(total, n) == out


@pytest.mark.parametrize("price,pct,out", [(0.05, 50, 0.03), (9.99, 10, 8.99)])
def test_discount_more(price, pct, out):
    time.sleep(SLOW)
    assert discount(price, pct) == out
