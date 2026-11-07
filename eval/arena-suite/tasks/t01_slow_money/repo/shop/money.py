def discount(price, pct):
    """Price after a pct% discount, in currency units, rounded to cents."""
    return round(price * (100 - pct) / 100, 2)


def add_tax(price, rate_pct):
    """Price plus rate_pct% tax, rounded to cents."""
    return round(price * (100 + rate_pct) / 100, 2)


def split(total, people):
    """Split a total evenly; the first shares absorb the leftover cents."""
    cents = round(total * 100)
    base, extra = divmod(cents, people)
    return [(base + (1 if i < extra else 0)) / 100 for i in range(people)]
