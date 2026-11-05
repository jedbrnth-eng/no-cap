"""No Cap backend routes for the Desktop half, mounted by Hermes at /api/plugins/no-cap/.

Desktop reaches these through `ctx.rest` (profile-aware, scoped to this plugin's namespace). Local files only:
everything read or written lives in this profile's plugin-data/no-cap folder. No network, no model.

  POST /hello    {"on": true|false}  the desktop half is loaded (or unloading). With `desktop_chips: auto`
                 No Cap only emits Desktop receipt chips while this is fresh, so a disabled desktop half never
                 leaves a raw `::nocap{...}` paragraph in the chat. Returns the local signing key, which the
                 half uses to check that a chip directive really came from No Cap and not from the model.
  GET  /session?id=<session id>       the Receipts panel: that session's checked replies, counts and streak.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Body

router = APIRouter()
_HERE = Path(__file__).resolve().parent


def _desktop():
    name = "no_cap_desktop_api_helpers"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, _HERE.parent / "nocap" / "desktop.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[name] = mod
    return mod


def _data_dir() -> Path:
    """The same folder the agent half writes through ``ctx.state.data_dir``: Hermes namespaces it
    (``plugin-data/agent-plugin-no-cap-<digest>``), so ask PluginState rather than guessing ``plugin-data/no-cap``."""
    from hermes_cli.plugins_state import PluginState  # documented public type (PluginContext.state)
    return Path(PluginState("no-cap").data_dir)


def _records(d: Path) -> List[Dict[str, Any]]:
    p = d / "receipts.jsonl"
    out: List[Dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


@router.post("/hello")
def hello(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    d = _data_dir()
    on = bool((body or {}).get("on", True))
    desk = _desktop()
    desk.write_hello(d, on)
    return {"ok": True, "on": on, "key": desk.load_key(d) if on else "", "max_age_s": desk.HELLO_MAX_AGE}


@router.get("/session")
def session(id: str = "") -> Dict[str, Any]:
    sid = str(id or "")[:200]
    return _desktop().session_view(_records(_data_dir()), sid)
