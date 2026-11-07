import datetime as dt


def add_business_days(start, n):
    step = 1 if n >= 0 else -1
    day = start
    left = abs(n)
    while left:
        day += dt.timedelta(days=step)
        if day.weekday() < 5:
            left -= 1
    return day
