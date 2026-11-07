import pytest
from roman import to_roman


@pytest.mark.parametrize("n,r", [(1, "I"), (3, "III"), (4, "IV"), (9, "IX"), (14, "XIV"), (40, "XL"), (90, "XC"),
                                 (400, "CD"), (900, "CM"), (1994, "MCMXCIV"), (3999, "MMMCMXCIX"), (2024, "MMXXIV")])
def test_values(n, r):
    assert to_roman(n) == r


@pytest.mark.parametrize("n", [0, -1, 4000])
def test_range(n):
    with pytest.raises(ValueError):
        to_roman(n)
