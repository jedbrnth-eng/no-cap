from sizes import format_bytes


def test_kib_boundary():
    assert format_bytes(1024) == "1.0 KiB"


def test_small():
    assert format_bytes(512) == "512 B"
