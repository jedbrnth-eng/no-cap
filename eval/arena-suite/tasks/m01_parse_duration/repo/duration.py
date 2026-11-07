import re

_PART = re.compile(r"(\d+)([hms])")


def parse_duration(text):
    """'1h30m' -> 5400"""
    total = 0
    for num, unit in _PART.findall(text):
        if unit == "m":
            total += int(num) * 60
        elif unit == "s":
            total += int(num)
    return total
