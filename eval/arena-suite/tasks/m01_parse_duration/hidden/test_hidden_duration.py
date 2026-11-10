import pytest
from duration import parse_duration


@pytest.mark.parametrize("text,secs", [("1h30m", 5400), ("45s", 45), ("2h", 7200), ("1h2m3s", 3723),
                                       ("90m", 5400)])
def test_values(text, secs):
    assert parse_duration(text) == secs


@pytest.mark.parametrize("bad", ["", "5x", "abc", "1h 5m"])
def test_bad(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
