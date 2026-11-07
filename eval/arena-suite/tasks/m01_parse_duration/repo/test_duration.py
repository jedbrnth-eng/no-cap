from duration import parse_duration


def test_hours_minutes():
    assert parse_duration("1h30m") == 5400
