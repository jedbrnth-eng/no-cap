from csvline import split_csv_line


def test_quoted_comma():
    assert split_csv_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_plain():
    assert split_csv_line("x,y") == ["x", "y"]


def test_doubled_quote():
    assert split_csv_line('"say ""hi""",2') == ['say "hi"', "2"]


def test_empty_fields():
    assert split_csv_line('a,,"",b') == ["a", "", "", "b"]
