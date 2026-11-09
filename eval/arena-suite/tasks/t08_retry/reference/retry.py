def retry(fn, attempts=3):
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
    raise last
