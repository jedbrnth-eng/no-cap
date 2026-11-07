from decimal import Decimal, ROUND_HALF_UP


def _cents(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _d(x):
    return Decimal(str(x))


def discount(price, pct):
    """Price after a pct% discount, in currency units, rounded to cents."""
    return _cents(_d(price) * (100 - _d(pct)) / 100)


def add_tax(price, rate_pct):
    """Price plus rate_pct% tax, rounded to cents."""
    return _cents(_d(price) * (100 + _d(rate_pct)) / 100)


def split(total, people):
    """Split a total evenly; the first shares absorb the leftover cents."""
    cents = round(total * 100)
    base, extra = divmod(cents, people)
    return [(base + (1 if i < extra else 0)) / 100 for i in range(people)]
