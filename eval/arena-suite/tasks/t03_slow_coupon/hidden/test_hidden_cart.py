from cart import Cart


def test_coupon_once():
    c = Cart()
    c.add("tea", 4)
    c.add("cake", 6)
    c.apply_coupon(5)
    assert c.total() == 5


def test_floor_at_zero():
    c = Cart()
    c.add("gum", 1)
    c.apply_coupon(5)
    assert c.total() == 0
    e = Cart()
    e.apply_coupon(3)
    assert e.total() == 0


def test_qty_and_replace():
    c = Cart()
    c.add("pen", 2, qty=3)
    c.add("ink", 4)
    c.apply_coupon(1)
    assert c.total() == 9
    c.apply_coupon(4)
    assert c.total() == 6
