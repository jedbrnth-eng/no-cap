UNITS = ["KiB", "MiB", "GiB", "TiB"]


def format_bytes(n):
    if n < 1024:
        return f"{n} B"
    value = float(n)
    unit = "B"
    for u in UNITS:
        if value > 1024:
            value /= 1024
            unit = u
    return f"{value:.1f} {unit}"
