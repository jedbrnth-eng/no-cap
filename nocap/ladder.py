"""`hermes nocap demo --ladder` and `/nocap demo ladder`: run the Lie Ladder demo theater from the plugin.

The demo itself is demo/run_ladder.sh in the plugin folder. It builds a THROWAWAY Hermes home under /tmp (with
GIT_CONFIG_GLOBAL pointed at a throwaway file), starts the scripted stub model on 127.0.0.1, drives a real Hermes CLI
session through six lies and writes the HTML page, cast, GIF and PNGs. Nothing here touches the user's own home.

Subprocess: an argv list (`/bin/sh <plugin>/demo/run_ladder.sh`), never a shell string; the foreground CLI run has a
timeout, the slash command's background run is its own session with its output in a log file.
"""
from __future__ import annotations

import os
# argv lists only, a fixed script inside the plugin folder, never a shell string
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Optional

SCRIPT = Path(__file__).resolve().parents[1] / "demo" / "run_ladder.sh"
TIMEOUT = 1500
SH = "/bin/sh"
LOCAL_SURFACES = ("", "cli", "tui", "local")


def available() -> bool:
    return SCRIPT.is_file()


# The only variables the demo shell inherits (S10): what hermes, uv and a terminal need to start, plus the demo's own
# knobs. Provider keys, tokens, HERMES_HOME, PYTHONPATH and GIT_* never reach it (the model is the local stub).
ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM", "COLORTERM", "USER", "LOGNAME", "SHELL",
            "HERMES_AGENT_DIR", "NOCAP_DEMO_PORT", "NOCAP_DEMO_KEEP", "UV_CACHE_DIR")


def _env(out: Path) -> dict:
    env = {k: os.environ[k] for k in ENV_KEEP if os.environ.get(k)}
    env.setdefault("PATH", os.defpath)
    env["NOCAP_LADDER_OUT"] = str(out)
    return env


def default_out() -> Path:
    return Path(tempfile.mkdtemp(prefix="nocap-ladder-out."))  # the system temp dir (TMPDIR), created 0700


def run(out: Optional[str] = None) -> int:
    """Foreground: stream the demo's own output; returns its exit code."""
    if not available():
        print(f"Lie Ladder needs the demo folder next to the plugin ({SCRIPT} is missing).")
        return 2
    target = Path(out).expanduser().resolve() if out else default_out()
    print(f"🪜 Lie Ladder → {target} (throwaway Hermes home under /tmp; the scripted model is the only fake part)",
          flush=True)
    try:
        return subprocess.run([SH, str(SCRIPT)], env=_env(target), timeout=TIMEOUT,  # nosec B603
                              check=False).returncode
    except subprocess.TimeoutExpired:
        print(f"Lie Ladder timed out after {TIMEOUT}s")
        return 124


def start(platform: str = "") -> str:
    """Background, for the slash command. Local surfaces only: a chat platform never spawns a demo session."""
    if (platform or "").lower() not in LOCAL_SURFACES:
        return "🪜 The Lie Ladder runs a local demo session: start it from a terminal with `hermes nocap demo --ladder`."
    if not available():
        return f"🪜 Lie Ladder needs the demo folder next to the plugin ({SCRIPT} is missing)."
    target = default_out()
    log = target / "ladder.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        subprocess.Popen([SH, str(SCRIPT)], env=_env(target), stdout=fh, stderr=subprocess.STDOUT,  # nosec B603
                         stdin=subprocess.DEVNULL, start_new_session=True)
    return (f"🪜 Lie Ladder started in the background (throwaway Hermes home, scripted model on 127.0.0.1, a few "
            f"minutes). Output: {target} · log: {log} · open ladder.html when it says done.")
