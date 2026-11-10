import copy
from merge import deep_merge


def test_nested():
    a = {"db": {"host": "x", "port": 1}}
    b = {"db": {"port": 2}}
    assert deep_merge(a, b) == {"db": {"host": "x", "port": 2}}


def test_three_levels():
    a = {"a": {"b": {"c": 1, "d": 2}}}
    b = {"a": {"b": {"d": 3}, "e": 4}}
    assert deep_merge(a, b) == {"a": {"b": {"c": 1, "d": 3}, "e": 4}}


def test_inputs_untouched():
    a = {"db": {"host": "x", "port": 1}, "k": [1]}
    b = {"db": {"port": 2}, "k": [2]}
    a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
    out = deep_merge(a, b)
    out["db"]["host"] = "changed"
    assert a == a0 and b == b0


def test_dict_replaces_scalar():
    assert deep_merge({"x": 1}, {"x": {"y": 2}}) == {"x": {"y": 2}}
