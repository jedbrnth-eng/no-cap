"""No Cap backend routes for the Desktop half. dashboard/plugin_api.py (the plugin's one router) mounts this module,
so Hermes serves them under /api/plugins/no-cap/.

Desktop reaches these through `ctx.rest` (profile-aware, scoped to this plugin's namespace, behind the dashboard's
auth). Local files only: everything read or written lives in this profile's No Cap data folder. No network, no model.

  POST /hello    {"on": true|false}  the desktop half is loaded (or unloading). With `desktop_chips: auto`
                 No Cap only emits Desktop receipt chips while this is fresh, so a disabled desktop half never
                 leaves a raw `::nocap{...}` paragraph in the chat. Returns no key: there is none to hand out.
  POST /verify   {"session_id", "n", "s", "d"}  was this chip issued by No Cap for THIS chat? `session_id` is the
                 chat the directive is rendered in. {"ok": true, "turn_id"} or {"ok": false, "reason"}.
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
    # nocap/desktop.py imports its siblings (`from . import score`), so it is loaded as a submodule of the plugin's
    # nocap package under a private name, never as a lone file (that raised ImportError on every route)
    pkg_name = "no_cap_desktop_api_pkg"
    name = pkg_name + ".desktop"
    mod = sys.modules.get(name)
    if mod is None:
        if pkg_name not in sys.modules:
            pkg_dir = _HERE.parent / "nocap"
            spec = importlib.util.spec_from_file_location(pkg_name, pkg_dir / "__init__.py",
                                                          submodule_search_locations=[str(pkg_dir)])
            pkg = importlib.util.module_from_spec(spec)
            sys.modules[pkg_name] = pkg
            spec.loader.exec_module(pkg)
        mod = importlib.import_module(name)
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
    desk.drop_legacy_key(d)
    return {"ok": True, "on": on, "max_age_s": desk.HELLO_MAX_AGE}


@router.post("/verify")
def verify(body: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    b = body if isinstance(body, dict) else {}
    d = _data_dir()
    return _desktop().verify(b.get("session_id"), b.get("n"), b.get("s"), b.get("d"), records=lambda: _records(d))


@router.get("/session")
def session(id: str = "") -> Dict[str, Any]:
    sid = str(id or "")[:200]
    return _desktop().session_view(_records(_data_dir()), sid)
