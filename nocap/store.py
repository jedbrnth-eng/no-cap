"""Local receipt store: one JSON line per checked reply under the plugin's data dir."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

FILE = "receipts.jsonl"
MAX_BYTES = 20 * 1024 * 1024


class Store:
    def __init__(self, data_dir: Callable[[], Path], retention_days: Callable[[], int]):
        self._dir = data_dir
        self._retention = retention_days
        self._lock = threading.Lock()
        self._pruned = False

    @property
    def path(self) -> Path:
        return Path(self._dir()) / FILE

    def append(self, record: Dict[str, Any]) -> None:
        record = _scrub(record)  # every string is redacted before it touches disk
        with self._lock:
            p = self.path
            _private_dir(p.parent)
            if not self._pruned or (p.exists() and p.stat().st_size > MAX_BYTES):
                self._prune_locked()
                self._pruned = True
            with _open_private(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND) as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def records(self) -> List[Dict[str, Any]]:
        p = self.path
        if not p.exists():
            return []
        out = []
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
        return out

    def last(self, session_id: str = "", with_receipts: bool = True) -> Optional[Dict[str, Any]]:
        for rec in reversed(self.records()):
            if session_id and rec.get("session_id") != session_id:
                continue
            if with_receipts and not rec.get("receipts"):
                continue
            return rec
        return None

    def purge(self) -> int:
        with self._lock:
            n = len(self.records())
            for name in (FILE, "scorecard.png", "scorecard.svg"):
                try:
                    os.remove(Path(self._dir()) / name)
                except FileNotFoundError:
                    pass
            return n

    def _prune_locked(self) -> None:
        p = self.path
        if not p.exists():
            return
        days = max(1, int(self._retention() or 30))
        cutoff = time.time() - days * 86400
        keep = [r for r in self.records() if float(r.get("ts", 0) or 0) >= cutoff]
        if p.stat().st_size > MAX_BYTES:
            keep = keep[len(keep) // 2:]
        tmp = p.with_suffix(".tmp")
        with _open_private(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC) as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp, p)


def _private_dir(d: Path) -> None:
    """The store folder: created 0700, and tightened to 0700 if it already exists (it holds commands and claims)."""
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass


def _open_private(p: Path, flags: int):
    """Open a store file 0600 regardless of the umask (and tighten one created earlier with a looser mode)."""
    fd = os.open(p, flags, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, "w", encoding="utf-8")


IDENTITY_KEYS = {"session_id", "turn_id", "model", "platform", "type", "mode", "profile"}  # ids, never secrets: /cap joins on them


def _scrub(v: Any, key: str = "") -> Any:
    from .evidence import redact
    if isinstance(v, str):
        return v if key in IDENTITY_KEYS else redact(v)
    if isinstance(v, dict):
        return {k: _scrub(x, k) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_scrub(x) for x in v]
    return v
