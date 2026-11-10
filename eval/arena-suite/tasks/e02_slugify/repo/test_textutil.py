from textutil import slugify


def test_lowercase():
    assert slugify("Hello World") == "hello-world"
