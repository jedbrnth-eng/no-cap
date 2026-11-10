import datetime as dt


def add_business_days(start, n):
    return start + dt.timedelta(days=n)
