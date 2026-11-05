"""Time every parser on the ~100 KB adversarial inputs in tests/redos_inputs.py (best of 3, milliseconds).

    .venv/bin/python scripts/redos_timings.py [--all]

Prints the slowest cases; --all prints every case. Exit 1 if any case is over the 50 ms budget.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from nocap.claims import extract_claims, forged_stamps  # noqa: E402
from nocap.evidence import extract, parse_tests, redact, runner_segment  # noqa: E402
from redos_inputs import inputs  # noqa: E402

BUDGET_MS = 50.0
PARSERS = {
    "redact": lambda s: redact(s),
    "runner_segment": lambda s: runner_segment(s),
    "parse_tests": lambda s: parse_tests(s),
    "extract(cmd)": lambda s: extract("terminal", {"command": s}, {"output": "", "exit_code": 0}),
    "extract(output)": lambda s: extract("terminal", {"command": "pytest"}, {"output": s, "exit_code": 1}),
    "extract_claims": lambda s: extract_claims(s),
    "forged_stamps": lambda s: forged_stamps(s),
}


def best_ms(fn, s, reps=3):
    best = float("inf")
    for _ in range(reps):
        t = time.perf_counter()
        fn(s)
        best = min(best, (time.perf_counter() - t) * 1000)
        if best > 10 * BUDGET_MS:
            break  # clearly over budget: don't spend minutes confirming it
    return best


def main():
    rows = []
    for name, s in inputs().items():
        for pn, fn in PARSERS.items():
            rows.append((best_ms(fn, s), pn, name))
    rows.sort(reverse=True)
    show = rows if "--all" in sys.argv else rows[:15]
    for ms, pn, name in show:
        print(f"{ms:9.1f} ms  {pn:16} {name}")
    over = [r for r in rows if r[0] > BUDGET_MS]
    print(f"cases: {len(rows)}  over {BUDGET_MS:.0f} ms: {len(over)}  slowest: {rows[0][0]:.1f} ms")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
