"""`hermes nocap battery` / `/nocap battery`: the bundled synthetic battery through the real pipeline.

Each case (assets/battery.json, built by scripts/make_battery.py) is fed to a fresh Engine in a throwaway folder
through the same entry points the hooks call (post_tool_call → transform_llm_output), turn by turn, with no model and
no network; artifact checks are off (no repo). Every predicted stamp is matched to the case's gold stamp by kind, and
the report gives precision and recall for 🧢 and 🧾 with Wilson 95% intervals.

It is a synthetic battery, not the blind real-run number: the cases are invented and many were used while tuning.
"""
from __future__ import annotations

import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ASSET = Path(__file__).resolve().parent / "assets" / "battery.json"
BLIND = ("🧾 precision 0.88 (88/100) and 🧢 8 of 11 correct, on blind hand-labelled real agent runs "
         "(eval/README_METHOD.md)")
SCORED = ("CAP", "NO_CAP")


def load(path: Path = ASSET) -> List[Dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8")).get("cases") or [])


def _turns(calls: List[Dict[str, Any]]) -> List[Tuple[Any, List[Dict[str, Any]]]]:
    """Calls grouped by turn: numbered/previous turns first (in order), the current turn last."""
    order: Dict[Any, List[Dict[str, Any]]] = {}
    for c in calls:
        t = c.get("turn", "current")
        order.setdefault(t, []).append(c)
    earlier = sorted((k for k in order if k != "current"), key=lambda k: int(k))
    return [(k, order[k]) for k in earlier] + [("current", order.get("current", []))]


def run_case(case: Dict[str, Any], root: Path) -> List[Dict[str, Any]]:
    from .engine import Engine
    d = root / case["id"]
    settings = {"show_uncertain": "all", "verify_artifacts": False}
    eng = Engine(lambda: d, lambda k, default=None: settings.get(k, default))
    sid = "battery-" + case["id"]
    receipts: List[Dict[str, Any]] = []
    for n, (turn, calls) in enumerate(_turns(case.get("calls") or []), 1):
        tid = f"t{n}"
        for c in calls:
            eng.on_tool(tool_name=c["tool"], args=c.get("args"), result=c.get("result"), status=c.get("status"),
                        session_id=sid, turn_id=tid)
        final = turn == "current"
        eng.on_reply(response_text=case["reply"] if final else "Done with that step.", session_id=sid, turn_id=tid,
                     model="battery", platform="cli")
        if final:
            last = eng.store.last(sid, with_receipts=False)
            if last and last.get("turn_id") == tid:
                receipts = [r for r in last.get("receipts") or [] if r.get("kind") != "unchecked"]
    return receipts


def _match(pred: List[Tuple[str, str]], gold: List[Tuple[str, str]]):
    used = [False] * len(pred)
    pairs, lone = [], []
    for g in gold:
        j = next((j for j, p in enumerate(pred) if not used[j] and p == g), None)
        if j is None:
            j = next((j for j, p in enumerate(pred) if not used[j] and p[0] == g[0]), None)
        if j is None:
            lone.append(g)
        else:
            used[j] = True
            pairs.append((g, pred[j]))
    return pairs, lone, [p for j, p in enumerate(pred) if not used[j]]


def run(cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cases = load() if cases is None else cases
    t0 = time.perf_counter()
    tally = {v: {"tp": 0, "fp": 0, "fn": 0} for v in SCORED}
    exact, misses = 0, []
    with tempfile.TemporaryDirectory(prefix="nocap-battery-") as tmp:
        for case in cases:
            pred = [(r["kind"], r["verdict"]) for r in run_case(case, Path(tmp))]
            gold = [tuple(g[:2]) for g in case.get("gold") or []]
            pairs, lone, extra = _match(pred, gold)
            for v in SCORED:
                tally[v]["tp"] += sum(1 for g, p in pairs if g[1] == v and p[1] == v)
                tally[v]["fp"] += sum(1 for g, p in pairs if p[1] == v and g[1] != v) + sum(1 for p in extra if p[1] == v)
                tally[v]["fn"] += sum(1 for g, p in pairs if g[1] == v and p[1] != v) + sum(1 for g in lone if g[1] == v)
            extra_ = [p for p in extra if not (p[1] == "NO_RECEIPT" and case.get("tolerate_no_receipt"))]
            if not ([1 for g, p in pairs if g != p] or lone or extra_):
                exact += 1
            else:
                misses.append({"id": case["id"], "gold": gold, "pred": pred})
    return {"n": len(cases), "tally": tally, "exact": exact, "misses": misses,
            "seconds": time.perf_counter() - t0, "sources": sorted({c.get("source", "") for c in cases})}


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def _rate(k: int, n: int) -> str:
    if n <= 0:
        return "n/a | n/a"
    lo, hi = wilson(k, n)
    return f"{k / n:.2f} ({k}/{n}) | {lo:.2f}–{hi:.2f}"


def report(res: Dict[str, Any]) -> str:
    label = {"CAP": "🧢 CAP", "NO_CAP": "🧾 NO CAP"}
    lines = ["## No Cap battery: synthetic cases", "",
             f"> **This is a synthetic battery, not the blind real-run number.** {res['n']} invented cases bundled with "
             "the plugin (seeded from tests/test_redteam_cases.py and eval/cases.py, plus cross-turn, PR and "
             "non-English cases), many of them used while tuning, so expect it to read higher than unseen real runs. "
             f"The published figures stay {BLIND}.", "",
             "| stamp | precision | 95% CI (Wilson) | recall | 95% CI (Wilson) |", "|---|---|---|---|---|"]
    for v in SCORED:
        t = res["tally"][v]
        lines.append(f"| {label[v]} | {_rate(t['tp'], t['tp'] + t['fp'])} | {_rate(t['tp'], t['tp'] + t['fn'])} |")
    lo, hi = wilson(res["exact"], res["n"])
    lines += ["", f"Cases where every stamp matches the gold label: {res['exact']}/{res['n']} "
              f"(95% CI {lo:.2f}–{hi:.2f}).",
              f"Ran in {res['seconds']:.1f} s through the real hook entry points (post_tool_call → "
              "transform_llm_output), no model, no network, in a throwaway folder.",
              "Precision = stamped claims of that kind that the gold agrees with; recall = gold claims of that kind "
              "that got the stamp. 🤔 is scored by neither."]
    if res["misses"]:
        shown = ", ".join(m["id"] for m in res["misses"][:25])
        more = f" (+{len(res['misses']) - 25} more)" if len(res["misses"]) > 25 else ""
        lines.append(f"Cases that differ from gold: {shown}{more}.")
    return "\n".join(lines)
