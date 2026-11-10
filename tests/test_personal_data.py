"""Personal-data gate: ignore terminal formatting, never whole recordings."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("personal_data", Path(__file__).resolve().parents[1] / "scripts/check_personal_data.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("text", [
    '\x1b[32m+@' + 'pytest.mark.skip(reason="x")',
    r'\u001b[32m+@' + 'pytest.mark.skip(reason="x")',
    '\x1b[32m+@' + 'pytest.mark.parametrize("x", [1])',
])
def test_decorator_after_terminal_diff_prefix_is_not_email(text):
    assert gate.findings(text) == []


@pytest.mark.parametrize("text", [
    'someone' + '@gmail.com',
    '/Users/' + 'probe/x',
    '/home/' + 'probe/x',
    'someone' + '@' + 'pytest.mark.skip',
    '\x1b[32m+@' + 'pytest.mark.skip(reason="x") ' + 'someone' + '@gmail.com',
    '\x1b[32m+@' + 'pytest.mark.skip(reason="x") /Users/' + 'probe/x',
])
def test_real_leak_still_fails(text):
    assert gate.findings(text)


@pytest.mark.parametrize("text", ['', 'test@example.com', '325892845+jedbrnth-eng@users.noreply.github.com', '@' + 'pytest.mark.skip', '/tmp/home/probe/x'])
def test_empty_and_allowed_near_misses(text):
    assert gate.findings(text) == []
