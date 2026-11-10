from words import word_count


def test_double_space():
    assert word_count("a  b") == 2
