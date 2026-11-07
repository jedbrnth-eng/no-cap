import pytest
from pager import page_count, page_slice


@pytest.mark.parametrize("total,per,pages", [(20, 10, 2), (21, 10, 3), (0, 10, 0), (1, 10, 1), (9, 3, 3)])
def test_count(total, per, pages):
    assert page_count(total, per) == pages


def test_slice():
    items = list(range(25))
    assert page_slice(items, 1, 10) == list(range(10))
    assert page_slice(items, 3, 10) == [20, 21, 22, 23, 24]


def test_bad_per_page():
    with pytest.raises(ValueError):
        page_count(5, 0)
    with pytest.raises(ValueError):
        page_slice([1], 1, 0)
