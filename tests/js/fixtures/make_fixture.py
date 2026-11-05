"""Regenerate tests/js/fixtures/directive.json: a real directive from nocap.desktop for the JS tests.

    .venv/bin/python tests/js/fixtures/make_fixture.py
tests/test_desktop_js_contract.py fails if this file drifts from what the Python side emits.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from nocap import desktop  # noqa: E402

KEY = "0" * 63 + "1"
RECEIPTS = [
    {"kind": "tests", "text": "All tests pass.", "verdict": "CAP", "cite": 1, "tool": "terminal", "cmd": "pytest -q",
     "exit": 1, "why": "", "quote": "3 failed, 41 passed in 0.52s", "claim": {}},
    {"kind": "pushed", "text": "pushed to main", "verdict": "CAP", "cite": 2, "tool": "terminal",
     "cmd": "git push origin feat/login", "exit": 0, "why": "", "quote": "feat/login -> feat/login", "claim": {}},
    {"kind": "deployed", "text": "the deploy is live", "verdict": "NO_RECEIPT", "cite": None, "tool": None, "cmd": "",
     "exit": None, "why": "no deploy command ran this turn", "quote": "", "claim": {}},
    {"kind": "tests", "text": "44 passed", "verdict": "NO_CAP", "cite": 3, "tool": "terminal", "cmd": "pytest -q",
     "exit": 0, "why": "", "quote": "44 passed in 0.50s", "claim": {}},
]


def build():
    return {"key": KEY, "directive": desktop.directive(RECEIPTS, KEY, "turn-1"), "receipts": RECEIPTS}


if __name__ == "__main__":
    out = Path(__file__).with_name("directive.json")
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)
