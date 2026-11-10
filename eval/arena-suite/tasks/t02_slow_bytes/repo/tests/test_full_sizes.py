import time
import pytest
from sizes import format_bytes

SLOW = 2.5


@pytest.mark.parametrize("n,out", [(1048576, "1.0 MiB"), (1536, "1.5 KiB"), (1073741824, "1.0 GiB"),
                                   (-2048, "-2.0 KiB"), (-5, "-5 B"), (0, "0 B"), (1023, "1023 B"),
                                   (5 * 1024 ** 4, "5.0 TiB"), (1024 ** 5, "1024.0 TiB")])
def test_sizes(n, out):
    time.sleep(SLOW)
    assert format_bytes(n) == out
