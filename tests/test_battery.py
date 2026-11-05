"""`hermes nocap battery` / `/nocap battery`: bundled synthetic cases through the real pipeline, under 10 s."""
import json
import time

from nocap import battery
from nocap.engine import Engine


def test_battery_runs_fast_and_says_it_is_synthetic(tmp_path):
    cases = battery.load()
    assert 90 <= len(cases) <= 140
    assert {c["source"] for c in cases} == {"eval/cases.py", "tests/test_redteam_cases.py", "battery"}
    t = time.perf_counter()
    res = battery.run(cases)
    assert time.perf_counter() - t < 10
    text = battery.report(res)
    assert "This is a synthetic battery, not the blind real-run number." in text
    assert "0.88 (88/100)" in text and "8 of 11" in text  # the published blind figures, unchanged
    assert "🧢 CAP" in text and "🧾 NO CAP" in text and "Wilson" in text
    cap = res["tally"]["CAP"]
    assert cap["tp"] / (cap["tp"] + cap["fp"]) >= 0.9  # a regression guard, not a headline number


def test_battery_leaves_the_user_store_alone(tmp_path):
    e = Engine(lambda: tmp_path, lambda k, d=None: d)
    out = e.nocap("battery")
    assert out.startswith("## No Cap battery") and not (tmp_path / "receipts.jsonl").exists()


def test_wilson():
    lo, hi = battery.wilson(88, 100)
    assert round(lo, 2) == 0.80 and round(hi, 2) == 0.93
    assert battery.wilson(0, 0) == (0.0, 1.0)
    lo, hi = battery.wilson(10, 10)
    assert hi == 1.0 and 0.69 < lo < 0.73


def test_bundled_cases_are_synthetic():
    blob = json.dumps(battery.load())
    assert "/Users/" not in blob and "/home/" not in blob  # invented repos (acme/shop) and hosts only


def test_cli_and_slash_command_registered(tmp_path):
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("nocap_battery_cli", root / "__init__.py",
                                                  submodule_search_locations=[str(root)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nocap_battery_cli"] = mod
    spec.loader.exec_module(mod)
    seen = {}

    class Sub:
        def __init__(self):
            self.names = []

        def add_parser(self, name, **kw):
            self.names.append(name)
            return type("P", (), {"add_argument": lambda *a, **k: None,
                                  "add_mutually_exclusive_group": lambda self, **k: self})()

    class Parser:
        def add_subparsers(self, **kw):
            seen["subs"] = Sub()
            return seen["subs"]

        def set_defaults(self, **kw):
            seen["func"] = kw["func"]

    class Ctx:
        state = type("S", (), {"data_dir": tmp_path})()

        def register_hook(self, *a, **k):
            pass

        def register_command(self, name, handler, **k):
            seen.setdefault("cmds", {})[name] = (handler, k.get("args_hint", ""))

        def register_cli_command(self, name, help, setup_fn, handler_fn):
            setup_fn(Parser())

        def get_config(self, key, default=None):
            return default

    mod.register(Ctx())
    assert "battery" in seen["subs"].names and "battery" in seen["cmds"]["nocap"][1]
    assert seen["cmds"]["nocap"][0]("battery").startswith("## No Cap battery")
