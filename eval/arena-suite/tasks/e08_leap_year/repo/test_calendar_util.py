from calendar_util import is_leap


def test_1900():
    assert is_leap(1900) is False


def test_2024():
    assert is_leap(2024) is True
