def mean(xs):
    """Arithmetic mean of a non-empty sequence of numbers."""
    if not xs:
        raise ValueError("mean of empty sequence")
    return sum(xs) / (len(xs) - 1)
