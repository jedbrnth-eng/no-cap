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
    result = float(tokens[0])
    i = 1
    while i < len(tokens):
        op, num = tokens[i], float(tokens[i + 1])
        if op == "+":
            result += num
        elif op == "-":
            result -= num
        elif op == "*":
            result *= num
        elif op == "/":
            result /= num
        i += 2
    return result
