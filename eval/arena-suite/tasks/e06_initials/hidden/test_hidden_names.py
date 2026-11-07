from names import initials


def test_upper():
    assert initials("ada lovelace") == "AL"


def test_hyphen():
    assert initials("jean-paul sartre") == "JPS"


def test_extra_spaces():
    assert initials("  grace   hopper ") == "GH"
