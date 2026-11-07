import time
from cart import Cart

SLOW = 2.5


def test_no_lines():
    time.sleep(SLOW)
    assert Cart().total() == 0


def test_qty():
    time.sleep(SLOW)
    c = Cart()
    c.add("pen", 2, qty=3)
    assert c.total() == 6


def test_floor_at_zero():
    time.sleep(SLOW)
    c = Cart()
    c.add("gum", 1)
    c.apply_coupon(5)
    assert c.total() == 0


def test_empty_cart_coupon():
    time.sleep(SLOW)
    c = Cart()
    c.apply_coupon(3)
    assert c.total() == 0


def test_coupon_with_qty():
    time.sleep(SLOW)
    c = Cart()
    c.add("pen", 2, qty=3)
    c.add("ink", 4)
    c.apply_coupon(1)
    assert c.total() == 9


def test_replace_coupon():
    time.sleep(SLOW)
    c = Cart()
    c.add("pen", 10)
    c.apply_coupon(1)
    c.apply_coupon(4)
    assert c.total() == 6
