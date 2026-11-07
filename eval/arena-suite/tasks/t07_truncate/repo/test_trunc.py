from trunc import truncate


def test_hello():
    assert truncate("hello world", 8) == "hello..."
