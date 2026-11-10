from textutil import slugify


def test_lowercase():
    assert slugify("Hello World") == "hello-world"


def test_collapses_runs():
    assert slugify("Hello,   World!!") == "hello-world"


def test_no_edge_hyphens():
    assert slugify("  --Tea & Biscuits--  ") == "tea-biscuits"


def test_digits_kept():
    assert slugify("Top 10 Tips") == "top-10-tips"
