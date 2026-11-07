import pytest
from stats import mean


def test_mean_three():
    assert mean([2, 4, 6]) == 4.0


def test_mean_single():
    assert mean([5]) == 5.0


def test_mean_floats():
    assert mean([1.5, 2.5]) == 2.0


def test_mean_empty_raises():
    with pytest.raises(ValueError):
        mean([])
