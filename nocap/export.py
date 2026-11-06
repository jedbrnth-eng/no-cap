"""Export the receipt store: `hermes nocap export --json|--csv` and `hermes nocap metrics --file <path>`.

Honesty as an SLO, without a new network surface: metrics are written to a file in the Prometheus text exposition
format (point node_exporter's textfile collector, or anything else, at it). There is no port and no listener.
Every claim, command and evidence string leaves through redact() (ids and model names are kept, as in the store), even though the store already redacted it on the way in, so a store line
written by hand or by an older version can't leak a secret through an export. CSV cells that a spreadsheet would
run as a formula are prefixed with a quote.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .evidence import redact
from .render import claim_text

FORMAT = "no-cap-receipts/1"
FIELDS = ("ts", "session_id", "turn_id", "model", "platform", "mode", "profile", "kind", "verdict", "stamped",
          "claim", "cite", "tool", "exit", "evidence", "why")
VERDICTS = ("NO_CAP", "CAP", "NO_RECEIPT")


def _s(v: Any) -> str:
    return redact(" ".join(str(v if v is not None else "").split()))


def _id(v: Any) -> str:
    """Ids are stored as they are (the store's own rule: ids, never secrets; /cap joins on them), so the export keeps
    them joinable instead of masking a long hex session id as if it were a token."""
    return " ".join(str(v if v is not None else "").split())[:200]


def rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for rec in records:
        if not isinstance(rec, dict) or rec.get("type", "reply") != "reply":
            continue
        for r in rec.get("receipts") or []:
            if not isinstance(r, dict) or r.get("verdict") not in VERDICTS:
                continue
            out.append({
                "ts": float(rec.get("ts") or 0), "session_id": _id(rec.get("session_id")),
                "turn_id": _id(rec.get("turn_id")), "model": _id(rec.get("model") or "unknown"),
                "platform": _id(rec.get("platform")), "mode": _id(rec.get("mode")), "profile": _id(rec.get("profile")),
                "kind": _s(r.get("kind")), "verdict": r["verdict"], "stamped": not r.get("hidden"),
                "claim": _s(claim_text(r))[:300], "cite": r.get("cite") if isinstance(r.get("cite"), int) else None,
                "tool": _s(r.get("tool")), "exit": r.get("exit") if isinstance(r.get("exit"), int) else None,
                "evidence": _s(r.get("cmd"))[:200], "why": _s(r.get("quote") or r.get("why"))[:200],
            })
    return out


def to_json(records: Iterable[Dict[str, Any]]) -> str:
    rs = rows(records)
    return json.dumps({"format": FORMAT, "generated": int(time.time()), "receipts": rs}, ensure_ascii=False,
                      indent=1) + "\n"


def _cell(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v  # spreadsheet formula injection guard
    return "" if v is None else v


def to_csv(records: Iterable[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows(records):
        w.writerow({k: _cell(r[k]) for k in FIELDS})
    return buf.getvalue()


def _label(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics(records: Iterable[Dict[str, Any]]) -> str:
    records = list(records)
    rs = rows(records)
    claims = Counter((r["model"], r["kind"], r["verdict"]) for r in rs)
    per_model = Counter(r["model"] for r in rs)
    caps = Counter(r["model"] for r in rs if r["verdict"] == "CAP")
    proven = Counter(r["model"] for r in rs if r["verdict"] == "NO_CAP")
    replies = Counter(_id(rec.get("model") or "unknown") for rec in records
                      if isinstance(rec, dict) and rec.get("type", "reply") == "reply" and rec.get("receipts"))
    capped = Counter(_id(rec.get("model") or "unknown") for rec in records
                     if isinstance(rec, dict) and rec.get("type", "reply") == "reply"
                     and any(isinstance(x, dict) and x.get("verdict") == "CAP" for x in rec.get("receipts") or []))
    out = ["# HELP nocap_claims_total Claims checked by No Cap, by model, claim kind and verdict.",
           "# TYPE nocap_claims_total counter"]
    for (m, k, v), n in sorted(claims.items()):
        out.append(f'nocap_claims_total{{model="{_label(m)}",kind="{_label(k)}",verdict="{v}"}} {n}')
    out += ["# HELP nocap_replies_total Replies that carried at least one checked claim.",
            "# TYPE nocap_replies_total counter"]
    out += [f'nocap_replies_total{{model="{_label(m)}"}} {n}' for m, n in sorted(replies.items())]
    out += ["# HELP nocap_replies_capped_total Replies with at least one contradicted claim.",
            "# TYPE nocap_replies_capped_total counter"]
    out += [f'nocap_replies_capped_total{{model="{_label(m)}"}} {capped.get(m, 0)}' for m in sorted(replies)]
    out += ["# HELP nocap_cap_rate Claims contradicted / claims checked (read with nocap_claims_total for n).",
            "# TYPE nocap_cap_rate gauge"]
    out += [f'nocap_cap_rate{{model="{_label(m)}"}} {caps.get(m, 0) / n:.6f}' for m, n in sorted(per_model.items())]
    out += ["# HELP nocap_receipt_rate Claims proven / claims checked.", "# TYPE nocap_receipt_rate gauge"]
    out += [f'nocap_receipt_rate{{model="{_label(m)}"}} {proven.get(m, 0) / n:.6f}'
            for m, n in sorted(per_model.items())]
    out += ["# HELP nocap_store_records Lines in the local receipt store.", "# TYPE nocap_store_records gauge",
            f"nocap_store_records {len(records)}"]
    return "\n".join(out) + "\n"


def write_private(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` 0600, atomically (temp file + rename), creating the parent folder 0700."""
    path = Path(path).expanduser()
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory; give a file path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
