import pytest
from mathx import clamp


def test_above():
    assert clamp(15, 0, 10) == 10


def test_below_inside_edges():
    assert clamp(-3, 0, 10) == 0
    assert clamp(4, 0, 10) == 4
    assert clamp(10, 0, 10) == 10
    assert clamp(2.5, 2.5, 2.5) == 2.5


def test_bad_range():
    with pytest.raises(ValueError):
        clamp(1, 5, 0)
