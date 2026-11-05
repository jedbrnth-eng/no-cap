"""Score the claim checker on the labelled synthetic set. Usage: python eval/run_eval.py [--split dev|holdout|all] [--show]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import C  # noqa: E402
from nocap.claims import extract_claims  # noqa: E402
from nocap.evidence import extract  # noqa: E402
from nocap.verdict import judge  # noqa: E402

FLAG = {"CAP", "NO_RECEIPT"}


def run_case(case):
    evs = [extract(c["tool"], c["args"], c["result"], status=c.get("status"), index=i)
           for i, c in enumerate(case["calls"], 1)]
    return judge(extract_claims(case["reply"]), evs)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(cases, show=False):
    m = {k: [0, 0, 0] for k in ("claims", "flags", "caps")}
    agree = total = 0
    misses = []
    for case in cases:
        pred = [(r["kind"], r["verdict"]) for r in run_case(case)]
        gold = [tuple(g[:2]) for g in case["gold"]]
        used = [False] * len(pred)
        pairs, lone_gold = [], []
        for g in gold:
            j = next((j for j, p in enumerate(pred) if not used[j] and p[0] == g[0]), None)
            if j is None:
                lone_gold.append(g)
            else:
                used[j] = True
                pairs.append((g, pred[j]))
        lone_pred = [p for j, p in enumerate(pred) if not used[j]]
        m["claims"][0] += len(pairs)
        m["claims"][1] += len(lone_pred)
        m["claims"][2] += len(lone_gold)
        for g, p in pairs:
            total += 1
            agree += g[1] == p[1]
            for key, pos in (("flags", FLAG), ("caps", {"CAP"})):
                gp, pp = g[1] in pos, p[1] in pos
                m[key][0] += gp and pp
                m[key][1] += pp and not gp
                m[key][2] += gp and not pp
        for p in lone_pred:
            m["flags"][1] += p[1] in FLAG
            m["caps"][1] += p[1] == "CAP"
        for g in lone_gold:
            m["flags"][2] += g[1] in FLAG
            m["caps"][2] += g[1] == "CAP"
        if sorted(pred) != sorted(gold):
            misses.append((case["id"], case["reply"][:70], gold, pred))
    out = {k: prf(*v) + tuple(v) for k, v in m.items()}
    out["verdict_agreement"] = (agree / total if total else 1.0, agree, total)
    if show:
        for mm in misses:
            print("  MISS", mm)
    return out


def table(name, res, n):
    lines = [f"### {name} ({n} cases)", "", "| metric | precision | recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    label = {"claims": "claim found", "flags": "flagged (🧢 or 🤔)", "caps": "🧢 CAP only"}
    for k in ("claims", "flags", "caps"):
        p, r, f, tp, fp, fn = res[k]
        lines.append(f"| {label[k]} | {p:.3f} | {r:.3f} | {f:.3f} | {tp} | {fp} | {fn} |")
    a, agree, total = res["verdict_agreement"]
    lines.append(f"\nVerdict agreement on matched claims: {agree}/{total} ({a:.3f})\n")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    splits = ["dev", "holdout"] if a.split == "all" else [a.split]
    for s in splits:
        cs = [c for c in C if c["split"] == s]
        print(table(s, score(cs, a.show), len(cs)))
