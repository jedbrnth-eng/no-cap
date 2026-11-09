from cart import Cart


def test_coupon_once():
    c = Cart()
    c.add("tea", 4)
    c.add("cake", 6)
    c.apply_coupon(5)
    assert c.total() == 5
