from retry import retry


def test_call_count():
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("no")

    try:
        retry(boom, attempts=3)
    except RuntimeError:
        pass
    assert len(calls) == 3
