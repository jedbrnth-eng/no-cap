import datetime as dt
from bizdays import add_business_days


def test_friday_plus_one():
    assert add_business_days(dt.date(2026, 1, 2), 1) == dt.date(2026, 1, 5)
