from roman import to_roman


def test_four():
    assert to_roman(4) == "IV"


def test_three():
    assert to_roman(3) == "III"
