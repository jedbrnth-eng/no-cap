from merge import deep_merge


def test_nested():
    a = {"db": {"host": "x", "port": 1}}
    b = {"db": {"port": 2}}
    assert deep_merge(a, b) == {"db": {"host": "x", "port": 2}}
