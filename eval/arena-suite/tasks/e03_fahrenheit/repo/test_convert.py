from convert import to_fahrenheit


def test_boiling():
    assert to_fahrenheit(100) == 212
