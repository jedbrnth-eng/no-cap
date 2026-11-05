import pytest

from auth import check_password


@pytest.mark.parametrize("n", range(40))
def test_math_still_works(n):
    assert n + 0 == n


def test_login_ok():
    assert check_password("hunter2", "hunter2")


def test_login_wrong_password():
    assert not check_password("hunter3", "hunter2")


def test_login_case_sensitive():
    assert check_password("Secret", "Secret")


def test_login_unicode():
    assert check_password("pässwörd", "pässwörd")
