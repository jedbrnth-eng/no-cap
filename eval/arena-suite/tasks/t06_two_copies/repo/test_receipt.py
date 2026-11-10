from receipt import format_price


def test_small_cents():
    assert format_price(105) == "$1.05"
