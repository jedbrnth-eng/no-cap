from pager import page_count


def test_exact_multiple():
    assert page_count(20, 10) == 2
