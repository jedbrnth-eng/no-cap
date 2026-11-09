from intervals import merge


def test_unsorted():
    assert merge([[5, 8], [1, 3], [2, 4]]) == [[1, 4], [5, 8]]
