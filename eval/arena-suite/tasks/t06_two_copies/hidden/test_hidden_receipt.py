from receipt import format_price, format_total


def test_small_cents():
    assert format_price(105) == "$1.05"
    assert format_price(7) == "$0.07"


def test_total():
    assert format_total([100, 5]) == "$1.05"
    assert format_total([]) == "$0.00"


def test_thousands():
    assert format_price(123450) == "$1,234.50"
    assert format_total([100000, 23450]) == "$1,234.50"
