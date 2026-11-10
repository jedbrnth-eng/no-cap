"""Time budget: every parser stays under 50 ms on ~100 KB of adversarial input.

A regex that scans the rest of the input from every start position is quadratic: before this budget,
`parse_tests("1" * 100_000)` took about 200 s, and because `re` holds the GIL the whole Hermes process froze,
not just the hook thread. The inputs are in redos_inputs.py; `scripts/redos_timings.py` prints the table.
"""
import signal
import time

import pytest

from nocap.claims import _FORMER_FAILURE_PASS_RE, extract_claims, forged_stamps, stamp_like
from nocap.render import closer
from nocap.desktop import strip_model_directives
from nocap.engine import Engine
from nocap.surfaces.discord import claim_code, code
from nocap.evidence import (HEAD, TAIL, extract, failed_test_ids, home_tilde, parse_tests, redact, runner_files,
                            runner_segment, scan_window)
from nocap.lang import foreign_claims
from redos_inputs import inputs

BUDGET_MS = 50.0
PARSERS = {
    "redact": lambda s: redact(s),
    "runner_segment": lambda s: runner_segment(s),
    "parse_tests": lambda s: parse_tests(s),
    "extract(cmd)": lambda s: extract("terminal", {"command": s}, {"output": "", "exit_code": 0}),
    "extract(output)": lambda s: extract("terminal", {"command": "pytest"}, {"output": s, "exit_code": 1}),
    "formerly_failing_pass": lambda s: _FORMER_FAILURE_PASS_RE.search(s),
    "extract_claims": lambda s: extract_claims(s),
    "forged_stamps": lambda s: forged_stamps(s),
    "stamp_like": lambda s: stamp_like(s),  # judge review S1: the "No Cap issued no stamps" check
    "render.closer": lambda s: closer(s),  # judge review S11: fences, <!-- and <details> before the footer
    "strip_model_directives": lambda s: strip_model_directives(s),
    "extract(gh pr view)": lambda s: extract("terminal", {"command": "gh pr view 42"}, {"output": s, "exit_code": 1}),
    # a file-scoped run: the inventory-root check (one `cd` before the runner) scans the whole command
    "extract(file run)": lambda s: extract("terminal", {"command": "cd /nonexistent-nocap && pytest test_a.py && " + s,
                                                        "workdir": "/nonexistent-nocap"}, {"output": "", "exit_code": 0}),
    "foreign_claims": lambda s: foreign_claims(s),  # Chinese / Thai / Spanish (CJK and Thai shapes in redos_inputs)
    # the footer hint reads only the tail of each of the last 40 assistant messages
    "footer_hint": lambda s: Engine(lambda: "/nonexistent-nocap", lambda k, d=None: d)._footer_hint(
        [{"role": "assistant", "content": s}] * 40),
    "discord_code": lambda s: (code(s, 4000), claim_code(s, 4000)),
    # suite tampering (S4/S5): every edit shape a tool can carry, the failing-test ids and the runner names
    "extract(write_file test)": lambda s: extract("write_file", {"path": "tests/test_a.py", "content": s}, "{}"),
    "extract(patch test)": lambda s: extract("patch", {"path": "tests/test_a.py", "old_string": s,
                                                      "new_string": s[: len(s) // 2]}, "{}"),
    "extract(patch conftest)": lambda s: extract("patch", {"path": "conftest.py", "old_string": "", "new_string": s}, "{}"),
    "extract(patch config)": lambda s: extract("patch", {"path": "pyproject.toml", "old_string": s[::-1],
                                                        "new_string": s}, "{}"),
    "extract(apply_patch)": lambda s: extract("apply_patch", {"input": s}, "{}"),
    "failed_test_ids": lambda s: failed_test_ids(s),
    "runner_files": lambda s: runner_files("sh " + s),
    "home_tilde": lambda s: home_tilde(s),
}
INPUTS = inputs()
INPUTS["former_failure_prefixes"] = "failing " * 12_500 + "tests now pass"
INPUTS["former_failure_still"] = "failing tests now pass " + "still " * 16_000 + "fai"
INPUTS["former_failure_whitespace"] = "failing tests " + " " * 100_000 + "now pause"
# the forged-stamp precision pass (dogfood round): stamps, legends, quotes, backticks and "run in" asides en masse
INPUTS["stamp_legend"] = "🧾 NO CAP / 🧢 CAP or " * 5_000
INPUTS["stamp_nouns"] = "the 🧢 CAP stamp " * 6_000
INPUTS["stamp_lines"] = "🧾 NO CAP · x\n" * 7_000
INPUTS["backticks"] = "`" * 100_000
# judge review S1: receipt-shaped lines (stamp, quoted claim, citation) en masse, and near misses that make the shape
# scan try every quote opener (no closer, or no citation after the closer)
INPUTS["receipt_shaped_lines"] = "> 🧾 NO CAP “All tests pass” · call 1 → ok\n" * 2_500
INPUTS["receipt_open_quotes"] = ("🧾 NO CAP " + "“" * 60 + "\n") * 1_500
INPUTS["receipt_no_citation"] = ("🧢 CAP " + "“a” " * 40 + "\n") * 600
INPUTS["receipt_one_line"] = "🧾 NO CAP “x” " * 7_000
INPUTS["fences_and_details"] = "```\n<details>\n<!--\n~~~\n" * 4_000
INPUTS["open_backtick_runs"] = ("`" + "a" * 299 + " ") * 330
INPUTS["open_quotes"] = ("“" + "a" * 299 + "\n") * 330
INPUTS["run_in_paths"] = "done, run in /" + "a" * 100_000
INPUTS["run_in_many"] = "done, run in /a " * 6_000
INPUTS["footer_heads"] = "**🧾 No Cap** · 🧾 1 no cap\n" * 4_000
# suite tampering and command-line passwords (S4, S9)
INPUTS["skip_markers"] = "@pytest.mark.skip\n" * 5_500
INPUTS["skip_then_defs"] = "@pytest.mark.skip\ndef test_a():\n    assert x\n" * 2_200
INPUTS["test_defs"] = "def test_a():\n" * 7_000
INPUTS["js_its"] = "it.skip('a', f)\nit('" * 7_000
INPUTS["assert_lines"] = "    assert x == 1\n" * 5_500
INPUTS["diff_heads"] = "*** Update File: tests/test_a.py\n+ " "@pytest.mark.skip\n" * 2_000
INPUTS["unified_heads"] = "--- a/tests/t.py\n+++ b/tests/t.py\n" * 3_000
INPUTS["failed_ids"] = "FAILED tests/test_a.py::test_b - x\n" * 2_800
INPUTS["failed_long_path"] = "FAILED " + "a/" * 50_000
INPUTS["fail_js"] = "FAIL " + "a." * 50_000
INPUTS["unittest_fail"] = "FAIL: test_a (" + "a." * 50_000
INPUTS["env_filters"] = "PYTEST_ADDOPTS='-k x' " * 4_500
INPUTS["env_unclosed"] = "PYTEST_ADDOPTS='" + "-k " * 33_000
INPUTS["config_keys"] = "addopts = -k x\n" * 6_500
INPUTS["conftest_keys"] = "collect_ignore = []\n" * 5_000
INPUTS["curl_user"] = "curl -u a:" * 10_000
INPUTS["curl_users"] = "curl " + "-u a:b " * 14_000
INPUTS["mysql_p"] = "mysql " + "-p" * 50_000
INPUTS["sshpass"] = "sshpass -p " * 9_000
INPUTS["redis_cli"] = "redis-cli " * 10_000 + "-a x"
INPUTS["pass_flags"] = "--pass " * 14_000
INPUTS["runner_scripts"] = "./" + "a/" * 50_000 + "x.sh"
INPUTS["runner_dots"] = "./" + "a." * 50_000


class _Slow(Exception):
    pass


def _alarm(*_):
    raise _Slow()


def _calibration() -> float:
    """How much slower this machine is right now than the one the budget was set on (1.0 = same, capped at 4).
    A linear regex pass over 100 KB takes about 1 ms of CPU there; a slower or throttled core takes longer."""
    import re
    s, rx = "word 12 " * 12_500, re.compile(r"\b\w+\s+\d+\b")
    best = min(_timed(lambda: rx.findall(s)) for _ in range(5))
    return min(4.0, max(1.0, best / 1.0))


def _clock() -> float:
    """CPU time of this thread, in seconds. Wall time also counts the time a loaded machine spends running other
    processes: at load ~22 on 14 cores a 35 ms parse measured 70-120 ms of wall time and failed the budget, while
    the 1 ms calibration, short enough to finish inside one time slice, did not slow down with it. CPU time
    counts only the parser's own work, so a real slowdown still fails and a busy scheduler does not."""
    return time.thread_time()


def _timed(fn) -> float:
    t = _clock()
    fn()
    return (_clock() - t) * 1000


def _best_ms(fn, s, reps=5, limit_s=2.0):
    """Best of 5 in CPU ms. A CPU-time alarm (ITIMER_PROF, limit_s seconds) stops a quadratic case early."""
    old = signal.signal(signal.SIGPROF, _alarm)
    best = float("inf")
    try:
        for _ in range(reps):
            signal.setitimer(signal.ITIMER_PROF, limit_s)
            t = _clock()
            try:
                fn(s)
            except _Slow:
                return float("inf")
            finally:
                signal.setitimer(signal.ITIMER_PROF, 0)
            best = min(best, (_clock() - t) * 1000)
    finally:
        signal.signal(signal.SIGPROF, old)
    return best


@pytest.mark.parametrize("shape", sorted(INPUTS))
@pytest.mark.parametrize("parser", sorted(PARSERS))
def test_parser_time_budget(parser, shape):
    ms = _best_ms(PARSERS[parser], INPUTS[shape])
    scale = _calibration()  # measured next to the case, so a burst of load elsewhere scales both
    if ms >= BUDGET_MS * scale:  # one retry after a pause: a stretch on a slower core is not a regression
        time.sleep(0.2)
        ms, scale = _best_ms(PARSERS[parser], INPUTS[shape]), _calibration()
    assert ms < BUDGET_MS * scale, f"{parser} on {shape!r}: {ms:.1f} ms (budget {BUDGET_MS * scale:.0f} ms)"


def _spin(cpu_s: float) -> None:
    end = time.thread_time() + cpu_s
    while time.thread_time() < end:
        pass


def test_budget_clock_ignores_time_off_cpu():
    """A loaded machine preempts the test thread; that wait is not parser time. Sleeping is the same
    as being descheduled, so it must not count (wall-clock timing failed this suite at load ~22)."""
    assert _best_ms(lambda s: time.sleep(0.15), "", reps=1) < 20
    assert _timed(lambda: time.sleep(0.15)) < 20  # the calibration uses the same clock


def test_budget_clock_still_counts_cpu_work():
    """The fix must not hide a real slowdown: work done on the CPU is measured in full."""
    assert _best_ms(lambda s: _spin(0.12), "", reps=1) >= 100


def test_runaway_parser_is_cut_by_the_cpu_alarm():
    """A quadratic case is still stopped early (and reported as inf), by CPU time, not wall time."""
    assert _best_ms(lambda s: _spin(5.0), "", reps=1, limit_s=0.2) == float("inf")
    assert _best_ms(lambda s: time.sleep(0.3), "", reps=1, limit_s=0.2) < 20  # waiting is not running


def test_scan_window_keeps_head_tail_and_middle_summaries():
    middle = ("noise line\n" * 20_000) + "test result: FAILED. 3 passed; 1 failed; 0 ignored\n" + ("noise\n" * 20_000)
    text = "HEAD-MARK\n" + middle + "TAIL-MARK\n"
    assert len(text) > HEAD + TAIL
    w = scan_window(text)
    assert len(w) <= HEAD + TAIL + 70_000
    assert w.startswith("HEAD-MARK") and w.rstrip().endswith("TAIL-MARK")
    assert "test result: FAILED. 3 passed; 1 failed" in w  # a failing crate in the middle is not dropped
    assert scan_window("short") == "short"


def test_failure_in_the_middle_of_a_huge_output_still_counts():
    out = ("test result: ok. 5 passed; 0 failed; 0 ignored\n" + "x" * 70 + "\n") * 3000
    out += "test result: FAILED. 3 passed; 2 failed; 0 ignored\n"
    out += ("y" * 70 + "\n") * 3000 + "test result: ok. 9 passed; 0 failed; 0 ignored\n"
    ev = extract("terminal", {"command": "cargo test"}, {"output": out, "exit_code": 101})
    assert any(t["failed"] for t in ev["tests"])


def test_huge_single_line_is_fast_and_still_parses_the_summary():
    out = "." * 300_000 + "\n=== 3 failed, 41 passed in 0.12s ===\n"
    ms = _best_ms(lambda s: extract("terminal", {"command": "pytest"}, {"output": s, "exit_code": 1}), out)
    assert ms < BUDGET_MS * _calibration()
    ev = extract("terminal", {"command": "pytest"}, {"output": out, "exit_code": 1})
    assert ev["tests"][-1]["failed"] == 3 and ev["tests"][-1]["passed"] == 41


def test_windowed_failing_run_with_green_tail_is_not_a_receipt():
    from nocap.claims import extract_claims
    from nocap.verdict import NO_CAP, judge
    out = "noise\n" * 40_000 + "test result: ok. 9 passed; 0 failed; 0 ignored\n"
    ev = extract("terminal", {"command": "cargo test"}, {"output": out, "exit_code": 101}, index=1)
    assert ev["windowed"]
    r = judge(extract_claims("All tests pass."), [ev])
    assert r and r[0]["verdict"] != NO_CAP


def test_cut_command_with_unterminated_heredoc_is_not_a_test_run():
    body = "pytest -q\n" * 3000  # file content that looks like commands, cut before its EOF line
    ev = extract("terminal", {"command": "cat > notes.txt <<'EOF'\n" + body + "EOF\n"}, {"output": "", "exit_code": 0})
    assert not ev["test_cmd"]
    assert runner_segment("cat > a <<EOF\npytest\nEOF\n&& pytest -q") == "pytest -q"
