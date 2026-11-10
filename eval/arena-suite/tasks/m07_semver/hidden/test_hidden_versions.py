import pytest
from versions import compare_versions


@pytest.mark.parametrize("a,b,r", [("1.10.0", "1.9.0", 1), ("1.9.0", "1.10.0", -1), ("2.0.0", "2.0.0", 0),
                                   ("1.2", "1.2.0", 0), ("1.2.0", "1.2", 0), ("1.2.1", "1.2", 1), ("0.9", "0.10", -1)])
def test_cmp(a, b, r):
    assert compare_versions(a, b) == r
