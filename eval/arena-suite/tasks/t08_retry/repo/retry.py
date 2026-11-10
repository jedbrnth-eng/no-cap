def retry(fn, attempts=3):
    for _ in range(attempts + 1):
        try:
            return fn()
        except Exception:
            pass
    return None
