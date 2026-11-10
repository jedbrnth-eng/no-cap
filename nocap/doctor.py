"""`/nocap doctor` (any surface) and `hermes nocap doctor` (terminal): setup checks that explain why a stamp
might not show. Read-only except one probe file in the store directory, removed straight away.

Checks: another plugin that also rewrites replies (transform_llm_output: only one rewrite survives a turn),
whether /cap may inject its steer (allow_gateway_injection), whether the store can be written, and the
current mode and show_uncertain level.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def reply_transform_owners(home: Path) -> List[str]:
    """Other installed plugins that declare transform_llm_output. Only one reply rewrite survives a turn."""
    owners = []
    for manifest in sorted(Path(home, "plugins").glob("*/plugin.yaml")) + sorted(
            Path(home, "plugins").glob("*/*/plugin.yaml")):
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"(?m)^name:\s*['\"]?([\w.-]+)", text)
        name = m.group(1) if m else manifest.parent.name
        if name == "no-cap":
            continue
        if re.search(r"(?m)^\s*-\s*['\"]?transform_llm_output\b", text):
            owners.append(name)
    return sorted(set(owners))


def store_writable(store_path: Path) -> Optional[str]:
    """None when a file can be created next to the store (and the store itself is writable), else the error."""
    try:
        d = Path(store_path).parent
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".nocap-doctor-", dir=d)
        os.close(fd)
        os.remove(probe)
        if Path(store_path).exists() and not os.access(store_path, os.W_OK):
            return f"{store_path} is read-only"
        return None
    except OSError as exc:
        return str(exc)


def ledger_turns(path: Path, limit: int = 50 * 1024 * 1024) -> int:
    """Turns the reply hook recorded (ledger.jsonl "turn" lines). Read-only; 0 when there is no ledger."""
    try:
        if not Path(path).is_file() or Path(path).stat().st_size > limit:
            return 0
        n = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"type": "turn"' in line or '"type":"turn"' in line:
                    n += 1
        return n
    except OSError:
        return 0


# Seen in the final dogfood run (Hermes 0.23.0): the classic CLI sends an injected steer through the local gateway;
# the agent answers it, but nothing of that turn prints in the CLI. /nocap shows its receipts and the re-score.
CLI_INJECT_NOTE = ("ℹ️ Classic CLI: the agent's answer to an injected steer can run without printing here "
                   "(Hermes sends it through the local gateway). Type /nocap to see its receipts and the re-score.")


def run(home: Path, mode: str, entry: Dict[str, Any], store_path: Path, records: List[Dict[str, Any]],
        enabled: Callable[[str], Any], show_uncertain: str = "off") -> str:
    return check(home, mode, entry, store_path, records, enabled, show_uncertain)[0]


def check(home: Path, mode: str, entry: Dict[str, Any], store_path: Path, records: List[Dict[str, Any]],
          enabled: Callable[[str], Any], show_uncertain: str = "off",
          desktop_line: Optional[str] = None) -> Tuple[str, int]:
    """The report and its problem count (`hermes nocap doctor` exits 1 when the count is not zero)."""
    lines = ["🩺 **No Cap doctor**"]
    problems = 0
    others = reply_transform_owners(home)
    live = [o for o in others if enabled(o) is not False]
    if live:
        problems += 1
        lines.append(f"⚠️ Other reply transforms installed: {', '.join(live)}. Hermes keeps only the first plugin's "
                     "rewrite each turn, so one footer can silently replace the other. Disable one, or run No Cap in "
                     "quiet mode and read receipts with /nocap.")
    else:
        lines.append("✅ No other plugin rewrites replies (transform_llm_output).")
    lines.append(f"✅ Mode: {mode}" + (" (pre_verify nudges coding turns, at most 2 per turn)" if mode == "strict"
                                      else "") + f" · show_uncertain: {show_uncertain}")
    if entry.get("allow_gateway_injection") is True:
        lines.append("✅ /cap may send its steer into gateway-backed sessions (allow_gateway_injection is on). "
                     "In the classic CLI the agent's answer can run without printing there: /nocap shows it.")
    else:
        lines.append("ℹ️ /cap can only send its steer itself where Hermes runs plugins inside a local CLI. Gateway-"
                     "backed sessions (Discord, Telegram, TUI, Desktop, and the classic CLI on Hermes builds that "
                     "route it through the local gateway) need plugins.entries.no-cap.allow_gateway_injection: true "
                     "(`hermes config set plugins.entries.no-cap.allow_gateway_injection true`). "
                     "Until then /cap prints the steer for you to paste. In the classic CLI pasting shows the whole "
                     "answer; an injected one can run without printing there (/nocap shows it).")
    err = store_writable(store_path)
    if err:
        problems += 1
        lines.append(f"❌ Store not writable: {err}. Replies still go out unchanged, but nothing is recorded, so /cap,"
                     " /nocap and /capscore have nothing to work with.")
    else:
        lines.append(f"✅ Store writable: {store_path}")
    replies = [r for r in records if r.get("type", "reply") == "reply"]
    platforms = sorted({str(r.get("platform") or "?") for r in replies})
    turns = ledger_turns(Path(store_path).parent / "ledger.jsonl")
    lines.append(f"ℹ️ Reply hook saw {turns} turn{'s' if turns != 1 else ''} (ledger) · {len(replies)} checked "
                 f"repl{'ies' if len(replies) != 1 else 'y'} stored"
                 + (f", platforms seen: {', '.join(platforms)}" if platforms else ""))
    if not replies and not turns:
        lines.append("ℹ️ Nothing recorded yet. No Cap only sees a model turn that ends with a reply: a profile whose "
                     "only activity is no-agent cron scripts, gateway reconnects or turns that failed before a reply "
                     "(HTTP 429, auth) records nothing, and that is expected. A turn with neither claims nor tool calls "
                     "is counted in the ledger only. Hooks load at session start: restart sessions that were already "
                     "running at install.")
    if desktop_line:
        lines.append(desktop_line)
    lines.append("✅ Network: none" + (" (except /cap HEAD checks: self_verify_http is on)"
                                        if (entry.get("settings") or {}).get("self_verify_http") else ""))
    lines.append(f"{problems} problem{'s' if problems != 1 else ''} found.")
    return "\n".join(lines), problems
