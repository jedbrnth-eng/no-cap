import re


def slugify(text):
    """'Hello, World!' -> 'hello-world'"""
    return re.sub(r"[^A-Za-z0-9]", "-", text.strip())
