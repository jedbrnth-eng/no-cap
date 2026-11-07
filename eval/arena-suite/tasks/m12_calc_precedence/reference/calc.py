import re

_TOKEN = re.compile(r"\s*(\d+|[-+*/()])")


def tokenize(expr):
    pos, out = 0, []
    expr = expr.strip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise ValueError(f"bad input at {pos}")
        out.append(m.group(1))
        pos = m.end()
    return out


def evaluate(expr):
    tokens = tokenize(expr)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def atom():
        tok = take()
        if tok == "(":
            value = expr_()
            if take() != ")":
                raise ValueError("expected )")
            return value
        return float(tok)

    def term():
        value = atom()
        while peek() in ("*", "/"):
            if take() == "*":
                value *= atom()
            else:
                value /= atom()
        return value

    def expr_():
        value = term()
        while peek() in ("+", "-"):
            if take() == "+":
                value += term()
            else:
                value -= term()
        return value

    result = expr_()
    if pos != len(tokens):
        raise ValueError("trailing input")
    return result
