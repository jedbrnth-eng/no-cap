"""eval/recompute.py rebuilds every README eval number from eval/data/, and the README quotes each one exactly."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_readme_numbers_match_recompute():
    p = subprocess.run([sys.executable, str(ROOT / "eval" / "recompute.py"), "--check"], capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "numbers quoted exactly" in p.stdout
