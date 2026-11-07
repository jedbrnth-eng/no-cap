from mathx import clamp


def test_above():
    assert clamp(15, 0, 10) == 10
