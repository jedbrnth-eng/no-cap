from words import word_count


def test_double_space():
    assert word_count("a  b") == 2


def test_newlines_tabs():
    assert word_count("one\ttwo\nthree  four") == 4


def test_blank():
    assert word_count("") == 0
    assert word_count("   \n ") == 0


def test_edges():
    assert word_count("  lead and trail  ") == 3
