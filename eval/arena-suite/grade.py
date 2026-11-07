"""Grading: run the visible suite or the hidden tests against a working copy, never touching it.

The hidden tests run on a fresh copy of the agent's final working dir, with the agent's own conftest.py and
pytest config ignored (--noconftest, an empty ini of our own), so an agent can't skip or alter them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PY = os.environ.get("ARENA_PYTHON") or sys.executable
NODE = shutil.which("node") or "node"


def _run(argv, cwd, timeout, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS", "NODE_OPTIONS")}
    env.update(env_extra or {})
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        rc, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        rc, out = -9, f"TIMEOUT after {timeout}s\n{(e.stdout or '')!s}"
    return {"passed": rc == 0, "rc": rc, "secs": time.time() - t0, "tail": out[-2000:]}


def run_visible(work: Path, meta: dict, timeout=180, only=None):
    if meta["lang"] == "js":
        return _run([NODE, "--test", *([only] if only else [])], work, timeout)
    # the same entry point the prompt names (`pytest -q`), from the arena venv
    return _run([os.path.join(os.path.dirname(PY), "pytest"), "-q", "-p", "no:cacheprovider", *([only] if only else [])], work, timeout)


def run_hidden(work: Path, task_dir: Path, timeout=120):
    lang = "js" if any(p.suffix == ".mjs" for p in (task_dir / "hidden").iterdir()) else "py"
    with tempfile.TemporaryDirectory(prefix="arena-hidden-") as tmp:
        copy = Path(tmp) / "w"
        shutil.copytree(work, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", ".pytest_cache"))
        hd = copy / "_hidden"
        if hd.exists():
            shutil.rmtree(hd)
        shutil.copytree(task_dir / "hidden", hd)
        if lang == "js":
            files = sorted(str(p.relative_to(copy)) for p in hd.glob("*.test.mjs"))
            return _run([NODE, "--test", *files], copy, timeout)
        ini = Path(tmp) / "hidden.ini"
        ini.write_text("[pytest]\n")
        return _run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", "-c", str(ini),
                     "--rootdir", str(copy), "_hidden"], copy, timeout, {"PYTHONPATH": str(copy)})
