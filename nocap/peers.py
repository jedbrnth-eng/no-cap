"""Peer reply transforms No Cap composes with, so its footer never silently drops their rewrite.

Hermes keeps only the first ``transform_llm_output`` rewrite of a turn. When No Cap appends receipts, a reply
formatter such as Skim (bold highlights + TL;DR) loses its rewrite. So, only on turns where No Cap rewrites, it runs
Skim on the reply BODY (never the footer) before composing the footer.

Skim is found generically and every step fails open (the body is returned unchanged):
  - Hermes must report it loaded and enabled for this profile (``ctx.has_plugin``); hosts without that probe skip it;
  - its directory is the one under ``<HERMES_HOME>/plugins`` whose plugin.yaml says ``name: skim``;
  - only its pure ``skimlib`` package is imported, under a private module name, so nothing collides in sys.modules
    and the plugin's own ``register`` never runs twice;
  - ``skimlib.glue.transform(get, response_text=, platform=)`` reads Skim's own settings
    (``plugins.entries.<id>.settings``, legacy ``config``), so ``/skim off``, intensity and skip_platforms all apply.
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("hermes_plugins.no_cap")

SKIM = "skim"
_PREFIX = "_nocap_peer_skim_"
_LOCK = threading.Lock()
_CACHE: Dict[str, Tuple[Tuple[float, ...], Any]] = {}


def find_plugin(home: Path, name: str) -> Optional[Path]:
    """The plugin directory under ``home/plugins`` whose manifest is named ``name`` (folder name as fallback)."""
    base = Path(home) / "plugins"
    found = None
    for manifest in sorted(base.glob("*/plugin.yaml")) + sorted(base.glob("*/*/plugin.yaml")):
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"(?m)^name:\s*['\"]?([\w.-]+)", text)
        if (m.group(1) if m else manifest.parent.name) == name:
            if manifest.parent.name == name:
                return manifest.parent
            found = found or manifest.parent
    return found


def _load_glue(plugin_dir: Path) -> Any:
    """``skimlib.glue`` of that install, imported under a private name (cached; reloaded when its files change)."""
    lib = plugin_dir / "skimlib"
    stamp = tuple(p.stat().st_mtime for p in sorted(lib.glob("*.py")))
    key = str(lib.resolve())
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        pkg = _PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        for name in [m for m in sys.modules if m == pkg or m.startswith(pkg + ".")]:
            sys.modules.pop(name, None)
        try:
            spec = importlib.util.spec_from_file_location(pkg, lib / "__init__.py", submodule_search_locations=[str(lib)])
            if spec is None or spec.loader is None:
                raise ImportError(f"no importable skimlib in {plugin_dir}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[pkg] = mod
            spec.loader.exec_module(mod)
            glue = importlib.import_module(pkg + ".glue")
        except Exception:
            for name in [m for m in sys.modules if m == pkg or m.startswith(pkg + ".")]:
                sys.modules.pop(name, None)
            raise
        _CACHE[key] = (stamp, glue)
        return glue


def _settings(config: Dict[str, Any], ids) -> Callable[[str, Any], Any]:
    entries = ((config.get("plugins") or {}).get("entries") or {}) if isinstance(config, dict) else {}
    entry: Dict[str, Any] = {}
    for pid in ids:
        if isinstance(entries.get(pid), dict):
            entry = entries[pid]
            break
    raw_settings, raw_legacy = entry.get("settings"), entry.get("config")
    settings: Dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else {}
    legacy: Dict[str, Any] = raw_legacy if isinstance(raw_legacy, dict) else {}

    def get(key: str, default: Any = None) -> Any:
        if key in settings:
            return settings[key]
        return legacy.get(key, default)
    return get


class SkimPeer:
    """``__call__(body, platform) -> body`` with Skim's highlighting, or ``body`` unchanged. Never raises."""

    def __init__(self, loaded: Callable[[str], Any], home: Callable[[], Path],
                 config: Callable[[], Dict[str, Any]]):
        self.loaded, self.home, self.config = loaded, home, config

    def __call__(self, body: str, platform: str = "") -> str:
        try:
            if not isinstance(body, str) or not body.strip() or self.loaded(SKIM) is not True:
                return body
            plugin_dir = find_plugin(Path(self.home()), SKIM)
            if plugin_dir is None or not (plugin_dir / "skimlib" / "glue.py").is_file():
                return body
            glue = _load_glue(plugin_dir)
            get = _settings(self.config() or {}, (plugin_dir.name, SKIM))
            out = glue.transform(get, response_text=body, platform=platform or "")
            return out if isinstance(out, str) and out.strip() else body
        except Exception as exc:  # fail open: today's reply, unhighlighted
            logger.warning("no-cap: skim highlighting skipped: %s", exc, exc_info=True)
            return body
