"""No Cap dashboard backend, mounted by Hermes at /api/plugins/no-cap/ (extending-the-dashboard.md, "Backend API routes").

  GET /board?agent=&model=&skill=&min_claims=&v=   the Cap Board: this profile's receipt store (every profile only with
                                                   the board.team_profiles opt-in), aggregated per agent, model and
                                                   skill (nocap/board.py). Pass the last ``version`` as ``v``
                                                   and an unchanged board answers ``{"unchanged": true}``, so the tab
                                                   can poll every few seconds for the cost of a few stat() calls.

Read-only: stores are opened "rb" and never written, locked or pruned from here. Local files only: no network, no
model. Plain ``def`` handlers, so FastAPI runs them in a worker thread and a cold read never blocks the dashboard's
event loop. No streaming (the tab polls), so the routes also work unchanged under ``plugins.isolation: host``.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter()
_ROOT = Path(__file__).resolve().parent.parent
_PKG = "no_cap_dashboard_nocap"
# A plugin has one dashboard manifest and one API router. Route modules beside this file that other No Cap features
# ship (the Desktop half's /hello, /verify and /session) are mounted here when present, so each feature keeps its own
# file and this one never needs editing to add them. Fixed names only: nothing is discovered by glob.
_ROUTE_MODULES = ("desktop_api",)


def _board():
    """nocap/board.py, imported as part of its package (it reuses the store's redaction) under a private name."""
    mod = sys.modules.get(_PKG + ".board")
    if mod is not None:
        return mod
    if _PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(_PKG, _ROOT / "nocap" / "__init__.py",
                                                      submodule_search_locations=[str(_ROOT / "nocap")])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = pkg
        spec.loader.exec_module(pkg)
    return importlib.import_module(_PKG + ".board")


def _settings() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly  # documented public module
        cfg = load_config_readonly() or {}
    except Exception:
        return {}
    entry = ((cfg.get("plugins") or {}).get("entries") or {}).get("no-cap") or {}
    return entry.get("settings") or {}


@router.get("/board")
def board(agent: str = "", model: str = "", skill: str = "", min_claims: int = 0, v: str = "") -> Dict[str, Any]:
    B = _board()
    st = _settings()
    extra = B.env_sources() + B.parse_sources(st.get("board_sources") or "")
    # This profile only unless board.team_profiles opts in to the team view (nocap/board.py: scoped_sources).
    sources, scope = B.scoped_sources(team=(st.get("board") or {}).get("team_profiles")
                                      if isinstance(st.get("board"), dict) else None,
                                      platform="dashboard", extra=extra)
    try:
        n = int(min_claims or st.get("board_min_claims") or B.MIN_CLAIMS)
    except (TypeError, ValueError):
        n = B.MIN_CLAIMS
    agent, model, skill = str(agent)[:120], str(model)[:120], str(skill)[:120]
    # Trends move with the clock even when no store changes: the minute is part of the version.
    key = f"{B.signature(sources)}|{scope['mode']}|{','.join(scope['profiles'])}|{agent}|{model}|{skill}|{n}|" \
          f"{int(time.time() // 60)}"
    version = hashlib.sha256(key.encode()).hexdigest()[:16]
    if v and v == version:
        return {"unchanged": True, "version": version}
    out = B.build_board(sources, agent=agent, model=model, skill=skill, min_claims=n)
    out["version"] = version
    out["scope"] = scope
    return out


def _include_route_modules() -> None:
    here = Path(__file__).resolve().parent
    for name in _ROUTE_MODULES:
        path = here / f"{name}.py"
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"no_cap_dashboard_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        router.include_router(mod.router)


_include_route_modules()
