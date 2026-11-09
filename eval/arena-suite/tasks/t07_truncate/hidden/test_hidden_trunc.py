import pytest
from trunc import truncate


def test_hello():
    assert truncate("hello world", 8) == "hello..."


@pytest.mark.parametrize("text", ["a" * 50, "the quick brown fox jumps", "xyz" * 7])
@pytest.mark.parametrize("width", [3, 4, 10, 15])
def test_never_longer(text, width):
    out = truncate(text, width)
    assert len(out) <= width
    assert out.endswith("...")


def test_fits_unchanged():
    assert truncate("short", 5) == "short"
    assert truncate("", 3) == ""


def test_bad_width():
    with pytest.raises(ValueError):
        truncate("abc", 2)
