from versions import compare_versions


def test_numeric():
    assert compare_versions("1.10.0", "1.9.0") == 1
