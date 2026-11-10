from calc import evaluate


def test_precedence():
    assert evaluate("2+3*4") == 14
