_VALUES = [(1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")]


def to_roman(n):
    if not 0 < n < 4000:
        raise ValueError("out of range")
    out = []
    for value, sym in _VALUES:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)
