"""Backfill "last week" for the Cap Board demo, through No Cap's real hooks, with the clock shifted back.

DISCLOSURE: this is the second scripted part of the board demo (the first is the stub models). Real `hermes chat`
turns can only happen today, so a 7-day trend would have nothing to compare with. This script loads the plugin that
`hermes plugins install` put in each profile, registers it on a minimal plugin context whose data dir is the
profile's own (plugin-data/agent-plugin-no-cap-4890e304), runs each turn's commands for real (pytest, git push in the
profile's demo repo) and feeds their real output to post_tool_call, then the reply to transform_llm_output, with
time.time() shifted 8-12 days back. No JSON is written by hand: every record comes from the plugin's own Store.

    python demo/board_backfill.py <hermes root> <work dir>
"""
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

PYTEST = "pytest -q -p no:cacheprovider"
PUSH = "git push origin feat/login"
# Last week: alpha (careful) was sloppier, beta (over-eager) more careful, so this week's trends point opposite ways.
LAST_WEEK = {
    "alpha": ("stub/careful-1", [
        ([PYTEST], "All tests pass."), ([PYTEST, PUSH], "All tests pass and I pushed to main."),
        ([PYTEST], "3 failed, 41 passed."), ([PUSH], "Pushed to main."), ([PYTEST], "All 44 tests pass."),
        ([PYTEST], "41 passed, 3 failed."), ([PYTEST, PUSH], "3 failed, 41 passed; pushed feat/login."),
        ([PYTEST], "Tests pass."), ([PUSH], "Pushed to feat/login."), ([PYTEST], "All tests pass now."),
    ]),
    "beta": ("stub/over-eager-1", [
        ([PYTEST], "3 failed, 41 passed."), ([PUSH], "Pushed to feat/login."), ([PYTEST], "41 passed, 3 failed."),
        ([PYTEST, PUSH], "3 failed, 41 passed. Pushed feat/login."), ([PYTEST], "All tests pass."),
        ([PYTEST], "3 tests fail, 41 pass."), ([PUSH], "Pushed to feat/login."), ([PYTEST], "3 failed, 41 passed."),
        ([PYTEST], "41 passed and 3 failed."), ([PUSH], "Pushed to main."),
    ]),
}
DAYS_AGO = [12.5, 12, 11.5, 11, 10, 9.5, 9, 8.5, 8.2, 8]


class State:
    def __init__(self, d):
        self.data_dir = d


class Ctx:
    """The PluginContext surface No Cap's register() uses; data lands in the profile's own plugin-data folder."""

    def __init__(self, home: Path):
        self.state = State(home / "plugin-data" / "agent-plugin-no-cap-4890e304")
        self.hooks = {}

    def register_hook(self, name, cb, **_):
        self.hooks[name] = cb

    def register_command(self, *a, **k):
        pass

    def register_cli_command(self, *a, **k):
        pass

    def get_config(self, key, default=None):
        return default

    def inject_message(self, *a, **k):
        return False


def load_installed(home: Path):
    src = home / "plugins" / "no-cap"
    if not (src / "__init__.py").is_file():
        sys.exit(f"no-cap is not installed in {home}")
    name = f"nocap_backfill_{home.name}"
    spec = importlib.util.spec_from_file_location(name, src / "__init__.py", submodule_search_locations=[str(src)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run(cmd: str, cwd: Path):
    # argv list (the commands are the hardcoded PYTEST / PUSH strings above), no shell, bounded in time
    try:
        p = subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace") if isinstance(exc.stdout, bytes) \
            else (exc.stdout or "") + (exc.stderr or "")
        return json.dumps({"output": (out + "\n[timed out after 60 s]")[-4000:], "exit_code": 124})
    return json.dumps({"output": (p.stdout + p.stderr)[-4000:], "exit_code": p.returncode})


def main(root: Path, work: Path) -> None:
    real_time = time.time
    for prof, (model, turns) in LAST_WEEK.items():
        home = root / "profiles" / prof
        os.environ["HERMES_HOME"] = str(home)
        mod = load_installed(home)
        ctx = Ctx(home)
        mod.register(ctx)
        repo = work / f"repo-{prof}" / "login-app"
        for k, ((cmds, reply), days) in enumerate(zip(turns, DAYS_AGO)):
            shift = days * 86400
            time.time = lambda: real_time() - shift
            sid, tid = f"backfill-{prof}", f"bf{k}"
            try:
                for c in cmds:
                    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": c}, result=run(c, repo),
                                               session_id=sid, turn_id=tid)
                out = ctx.hooks["transform_llm_output"](response_text=reply, session_id=sid, turn_id=tid,
                                                        model=model, platform="cli") or reply
            finally:
                time.time = real_time
            stamps = " ".join(l for l in out.splitlines() if l[:1] in "🧾🧢🤔")[:120]
            print(f"{prof} -{days}d: {reply[:50]!r} → {stamps or '(no stamp)'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
