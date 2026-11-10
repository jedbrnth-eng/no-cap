import re

_PART = re.compile(r"(\d+)([hms])")
_FULL = re.compile(r"(?:\d+[hms])+")
_UNIT = {"h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    """'1h30m' -> 5400"""
    if not text or not _FULL.fullmatch(text):
        raise ValueError(f"bad duration: {text!r}")
    return sum(int(num) * _UNIT[unit] for num, unit in _PART.findall(text))
