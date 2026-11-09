import copy
from intervals import merge


def test_unsorted():
    assert merge([[5, 8], [1, 3], [2, 4]]) == [[1, 4], [5, 8]]


def test_touching():
    assert merge([[1, 2], [2, 3]]) == [[1, 3]]


def test_contained_and_empty():
    assert merge([[1, 10], [2, 3]]) == [[1, 10]]
    assert merge([]) == []


def test_input_untouched():
    data = [[3, 4], [1, 3]]
    before = copy.deepcopy(data)
    merge(data)
    assert data == before
