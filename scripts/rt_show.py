"""Print gold vs predicted for red-team case ids: python scripts/rt_show.py A016 X003 ..."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import test_redteam_cases as T  # noqa: E402

ids = set(sys.argv[1:])
for case in T.CASES:
    if case["id"] in ids:
        out, receipts = T.run(case, Path(tempfile.mkdtemp()))
        print(T._show(case, receipts))
        print("calls:", [(c.get("tool"), str((c.get("args") or {}).get("command", ""))[:70],
                          str(c.get("result"))[:120]) for c in case.get("calls", [])][:6])
        print("-" * 80)
