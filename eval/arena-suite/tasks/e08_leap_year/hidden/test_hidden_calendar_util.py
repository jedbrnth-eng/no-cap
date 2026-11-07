import pytest
from calendar_util import is_leap


@pytest.mark.parametrize("year,leap", [(1900, False), (2024, True), (2000, True), (1600, True),
                                       (2100, False), (2023, False), (4, True)])
def test_gregorian(year, leap):
    assert is_leap(year) is leap
