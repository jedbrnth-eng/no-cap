import datetime as dt
import pytest
from bizdays import add_business_days

D = dt.date


@pytest.mark.parametrize("start,n,end", [
    (D(2026, 1, 2), 1, D(2026, 1, 5)),
    (D(2026, 1, 2), 6, D(2026, 1, 12)),
    (D(2026, 1, 5), 4, D(2026, 1, 9)),
    (D(2026, 1, 3), 1, D(2026, 1, 5)),
    (D(2026, 1, 3), 0, D(2026, 1, 3)),
    (D(2026, 1, 5), -1, D(2026, 1, 2)),
    (D(2026, 1, 7), -10, D(2025, 12, 24)),
])
def test_days(start, n, end):
    assert add_business_days(start, n) == end
