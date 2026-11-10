from shop.money import discount


def test_half_up():
    assert discount(10.05, 50) == 5.03


def test_simple():
    assert discount(100, 25) == 75.0
