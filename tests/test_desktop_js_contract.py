"""The JS tests read a directive the Python side really emits; this keeps that fixture honest."""
import importlib.util
import json
from pathlib import Path

FIX = Path(__file__).resolve().parent / "js" / "fixtures"


def test_js_fixture_is_what_python_emits_today():
    spec = importlib.util.spec_from_file_location("make_fixture", FIX / "make_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert json.loads((FIX / "directive.json").read_text(encoding="utf-8")) == mod.build()
