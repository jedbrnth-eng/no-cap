from pal import is_palindrome


def test_case():
    assert is_palindrome("Racecar")


def test_punctuation():
    assert is_palindrome("A man, a plan, a canal: Panama")
    assert is_palindrome("No 'x' in Nixon")


def test_negative_and_digits():
    assert not is_palindrome("ab")
    assert is_palindrome("12 21")
    assert not is_palindrome("123")


def test_empty():
    assert is_palindrome("")
