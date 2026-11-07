UNITS = ["KiB", "MiB", "GiB", "TiB"]


def format_bytes(n):
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 1024:
        return f"{sign}{n} B"
    value = float(n)
    unit = "B"
    for u in UNITS:
        if value >= 1024:
            value /= 1024
            unit = u
    return f"{sign}{value:.1f} {unit}"
