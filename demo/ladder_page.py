"""The Lie Ladder's annotated page: one self-contained HTML file built from the throwaway session's receipt store.

Self-contained: no scripts, no remote assets, images inlined as data: PNGs, and a Content-Security-Policy that
forbids everything else. Every string from the store (claims, commands, tool output quotes) is HTML-escaped, so a
hostile claim like `<img src=x onerror=...>` renders as text.

    python3 demo/ladder_page.py <receipts.jsonl> <session_id> <capture_dir> <out.html>
"""
from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STAMP = {"CAP": ("🧢 CAP", "cap"), "NO_CAP": ("🧾 NO CAP", "ok"), "NO_RECEIPT": ("🤔 NO RECEIPT", "nr")}
# Rungs whose 🧢 depends on the fabricated-artifact detector (git cat-file / refs), built in another PR.
ARTIFACT_KINDS = {"sha": "sha not found in repo", "merged": "no PR #… ref in the repo", "pr_opened": "no such PR ref"}
LADDER = ["the test lie", "the branch lie", "the fabricated SHA", "the phantom deploy", "the merge that never was"]
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

CSS = """
html,body{margin:0;background:#0E0F12;color:#E6E6E6;font:16px/1.5 -apple-system,'Helvetica Neue',Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 28px 64px}
h1{font-size:44px;margin:0 0 4px;letter-spacing:-.5px}h1 b{color:#FF3B30}
.sub{color:#8B8F98;margin:0 0 22px}.disc{background:#17191E;border-left:4px solid #FFB627;padding:10px 14px;margin:0 0 28px}
.rung{background:#17191E;border-radius:10px;padding:18px 22px;margin:0 0 22px}
.rung h2{margin:0 0 6px;font-size:22px}.rung h2 small{color:#8B8F98;font-weight:400;font-size:15px}
.ask{color:#8B8F98;margin:0 0 6px}.said{font-size:19px;margin:0 0 10px}
.calls{font:13px/1.45 ui-monospace,Menlo,monospace;color:#8B8F98;margin:0 0 10px}
.r{font:14px/1.5 ui-monospace,Menlo,monospace;padding:8px 10px;border-radius:6px;margin:0 0 6px;white-space:pre-wrap}
.cap{background:#3a1512;color:#FFB4AE}.ok{background:#0f2e1e;color:#9BF0C0}.nr{background:#33270c;color:#FFD98A}
.pend{border:1px dashed #FFB627;color:#FFD98A;padding:8px 10px;border-radius:6px;margin:6px 0 10px;font-size:14px}
img{max-width:100%;border-radius:6px;display:block;margin:10px 0 0}
pre.screen{font:12px/1.35 ui-monospace,Menlo,monospace;background:#0E0F12;padding:12px;overflow:auto;border-radius:6px}
.verdict img{background:#F4EEDF}footer{color:#8B8F98;font-size:14px;margin-top:30px}
code{font:14px ui-monospace,Menlo,monospace;background:#0E0F12;padding:1px 5px;border-radius:4px}
"""


def e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def pending(r: Dict[str, Any]) -> bool:
    """True when an artifact rung isn't 🧢 yet: show the honest current stamp and say what will catch it."""
    return r.get("kind") in ARTIFACT_KINDS and r.get("verdict") != "CAP"


def _img(data: Optional[bytes], alt: str) -> str:
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ""
    return f'<img alt="{e(alt)}" src="data:image/png;base64,{base64.b64encode(data).decode("ascii")}">'


def _receipt_line(r: Dict[str, Any]) -> str:
    from nocap.render import receipt_line
    try:
        return receipt_line(r)
    except Exception:
        return f"{STAMP.get(r.get('verdict'), ('?', ''))[0]} “{r.get('text', '')}”"


def build(records: List[Dict[str, Any]], session_id: str, snaps: Dict[str, str], images: Dict[str, bytes],
          verdict_png: Optional[bytes] = None, rungs: Optional[List[str]] = None, verdict_text: str = "",
          cast_note: str = "") -> str:
    from nocap.render import claim_text, dedupe
    rungs = rungs or []
    replies = [r for r in records if r.get("type", "reply") == "reply" and r.get("session_id") == session_id]
    body = [f"<h1>The Lie <b>Ladder</b></h1>",
            '<p class="sub">Five escalating lies, one real Hermes session, every one caught with a receipt.</p>',
            '<p class="disc">Disclosed: the model is scripted (<code>demo/stub_model.py</code>, an over-eager agent on '
            '127.0.0.1). Hermes, its tools, the shell, pytest, git and every stamp No Cap printed are real; this page '
            'is generated from the session\'s own receipt store.</p>']
    for i, rec in enumerate(replies, 1):
        key = f"{i:02d}-rung{i}"
        title = LADDER[i - 1] if i <= len(LADDER) else "an extra turn"
        ask = rungs[i - 1] if i <= len(rungs) else ""
        receipts = dedupe([r for r in rec.get("receipts") or [] if isinstance(r, dict) and r.get("verdict") in STAMP])
        said = " ".join(claim_text(r) for r in receipts) or "(no claims)"
        n = (rec.get("ledger") or {}).get("n", len(rec.get("calls") or []))
        cited = " · ".join(f"call {c.get('i')}: {c.get('cmd') or c.get('tool')}"
                           + (f" (exit {c.get('exit')})" if c.get("exit") is not None else "")
                           for c in rec.get("calls") or [])
        part = [f'<section class="rung"><h2>Rung {i} <small>· {e(title)}</small></h2>']
        if ask:
            part.append(f'<p class="ask">User: {e(ask)}</p>')
        part.append(f'<p class="said">Claim: “{e(said)}”</p>')
        part.append(f'<p class="calls">Tool calls this turn: {e(n)}' + (f" · cited {e(cited)}" if cited else
                                                                        " · none cited") + "</p>")
        for r in receipts:
            part.append(f'<div class="r {STAMP[r["verdict"]][1]}">{e(_receipt_line(r))}</div>')
            if pending(r):
                part.append(f'<div class="pend">Pending: the fabricated-artifact detector (being built in another '
                            f'PR) is what turns this into 🧢 “{e(ARTIFACT_KINDS[r["kind"]])}”. Today No Cap says '
                            f'{e(STAMP[r["verdict"]][0])}, honestly: nothing in the turn backs the claim, and it '
                            f'won\'t stamp 🧢 without a direct contradiction.</div>')
        pic = _img(images.get(key), f"Hermes terminal, rung {i}")
        if pic:
            part.append(pic)
        elif snaps.get(key):
            part.append(f'<pre class="screen">{e(snaps[key])}</pre>')
        part.append("</section>")
        body.append("\n".join(part))
    if verdict_png or verdict_text:
        body.append('<section class="rung verdict"><h2>The verdict <small>· /nocap verdict</small></h2>'
                    + (f'<p class="said">{e(verdict_text)}</p>' if verdict_text else "")
                    + _img(verdict_png, "Courtroom verdict card") + "</section>")
    body.append("<footer>Reproduce: <code>hermes nocap demo --ladder</code> (throwaway HERMES_HOME under /tmp, "
                "GIT_CONFIG_GLOBAL pointed at a throwaway file). " + e(cast_note) + "</footer>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{CSP}\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>No Cap · The Lie Ladder</title><style>{CSS}</style></head><body><main>"
            + "\n".join(body) + "</main></body></html>\n")


def main(argv: List[str]) -> int:
    store, session_id, cap_dir, out = Path(argv[0]), argv[1], Path(argv[2]), Path(argv[3])
    records = []
    for line in store.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    snaps = {p.name[:-len(".screen.txt")]: p.read_text(encoding="utf-8") for p in cap_dir.glob("*.screen.txt")}
    images = {p.stem: p.read_bytes() for p in cap_dir.glob("*.png")}
    vp = cap_dir / "verdict.png"
    vt = (cap_dir / "verdict.txt").read_text(encoding="utf-8").strip() if (cap_dir / "verdict.txt").exists() else ""
    from stub_model import RUNGS  # noqa: E402  (demo/ is on the path when run as a script)
    page = build(records, session_id, snaps, images, vp.read_bytes() if vp.exists() else None, RUNGS, vt,
                 "Recording: session.cast (asciinema v2) and ladder.gif.")
    out.write_text(page, encoding="utf-8")
    print(f"{out}: {len(page) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv[1:]))
