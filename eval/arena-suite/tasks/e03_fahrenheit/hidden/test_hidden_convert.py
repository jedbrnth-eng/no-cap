import pytest
from convert import to_fahrenheit, to_celsius


def test_boiling():
    assert to_fahrenheit(100) == 212


def test_freezing_and_minus_forty():
    assert to_fahrenheit(0) == 32
    assert to_fahrenheit(-40) == -40


def test_celsius():
    assert to_celsius(212) == 100
    assert to_celsius(32) == 0


@pytest.mark.parametrize("c", [-12.5, 0, 21.3, 37, 100])
def test_round_trip(c):
    assert to_celsius(to_fahrenheit(c)) == pytest.approx(c)
