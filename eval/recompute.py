#!/usr/bin/env python3
"""Rebuild every eval number the README quotes from the published files in eval/data/. Standard library only.

    python eval/recompute.py            # print every number with its source
    python eval/recompute.py --check    # also check that README.md quotes each one exactly (exit 1 if not)

Inputs (see eval/DATA.md for the columns):
  blind2_items.csv, blind3_items.csv   public SWE-rebench run ids, row hashes, both raters' labels, adjudicated label
  arena_episodes.csv, arena_stamps.csv one row per Arena episode / per No Cap stamp in annotate and strict episodes
  league_results.csv                   one row per Crew Cap League run (session ids dropped)
  coach_pairs.csv                      one row per matched held-out pair (control vs coach rules)
"""
from __future__ import annotations

import csv
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
README = HERE.parent / "README.md"


def rows(name):
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wilson(k, n, z=1.959964):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar(b, c):
    """Exact two-sided McNemar: binomial test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return po, (po - pe) / (1 - pe)


def ci2(k, n):
    lo, hi = wilson(k, n)
    return f"{lo:.2f}–{hi:.2f}"


def pct(k, n):
    return f"{100 * k / n:.0f}%"


def main(argv):
    out = {}  # name -> (value as the README prints it, how it was computed)

    def put(name, value, how):
        out[name] = (value, how)

    # ---- blind round 3 (01a1fab) ----
    b3 = rows("blind3_items.csv")
    nc = [x for x in b3 if x["stratum"] == "NO_CAP"]
    k = sum(x["final"] == "PROVEN" for x in nc)
    put("blind3.receipt_precision", f"{k / len(nc):.2f} ({k}/{len(nc)}, 95% CI {ci2(k, len(nc))})",
        "blind3 stratum NO_CAP, final == PROVEN")
    put("blind3.cap_items", str(sum(x["stratum"] == "CAP" for x in b3)), "blind3 stratum CAP (census of unseen runs)")
    po, kp = kappa([x["rater_claude"] for x in b3], [x["rater_gemini"] for x in b3])
    put("blind3.kappa", f"κ {kp:.2f} (raw agreement {po:.2f}, n = {len(b3)})", "Cohen's kappa, 4 labels, both raters")
    un = [x for x in b3 if x["stratum"] == "UNSTAMPED"]
    miss = [x for x in un if x["final"] in ("UNPROVEN", "CONTRADICTED")]
    put("blind3.misses", f"{len(miss)} of {len(un)} ({len(miss) / len(un):.2f}, 95% CI {ci2(len(miss), len(un))})",
        "blind3 stratum UNSTAMPED, final UNPROVEN or CONTRADICTED")
    sub = sum(x["error_class"] == "miss_unscoped_all_pass_after_subset" for x in miss)
    put("blind3.miss_subset", f"{sub} of {len(miss)}", "misses with error_class miss_unscoped_all_pass_after_subset")

    # ---- blind round 2 (7c6cbc0) and its re-score at c5cbad1 ----
    b2 = rows("blind2_items.csv")
    nc = [x for x in b2 if x["stratum"] == "NO_CAP"]
    k = sum(x["final"] == "PROVEN" for x in nc)
    put("blind2.receipt_precision", f"{k / len(nc):.2f} ({k}/{len(nc)}, 95% CI {ci2(k, len(nc))})",
        "blind2 stratum NO_CAP, final == PROVEN")
    cap = [x for x in b2 if x["stratum"] == "CAP"]
    kc = sum(x["final"] == "CONTRADICTED" for x in cap)
    put("blind2.cap", f"{kc} of {len(cap)}", "blind2 stratum CAP, final == CONTRADICTED")
    po, kp = kappa([x["rater_claude"] for x in b2], [x["rater_gemini"] for x in b2])
    put("blind2.kappa", f"κ {kp:.2f}", "Cohen's kappa, 4 labels, both raters")
    shown = [x for x in cap if x["rescore_c5cbad1_verdict"] == "CAP" and x["rescore_c5cbad1_shown"] == "y"]
    put("blind2.rescore_cap", f"{sum(x['final'] == 'CONTRADICTED' for x in shown)}/{len(shown)}",
        "blind2 CAP items still a visible 🧢 at c5cbad1, final == CONTRADICTED")
    vis = [x for x in nc if x["rescore_c5cbad1_verdict"] == "NO_CAP" and x["rescore_c5cbad1_shown"] == "y"]
    kv = sum(x["final"] == "PROVEN" for x in vis)
    put("blind2.rescore_receipt", f"{kv}/{len(vis)} = {kv / len(vis):.2f} (95% CI {ci2(kv, len(vis))})",
        "blind2 NO_CAP items still a visible 🧾 at c5cbad1, final == PROVEN")

    # ---- Arena ----
    st = rows("arena_stamps.csv")
    caps = [x for x in st if x["verdict"] == "CAP"]
    right = sum(x["visible_pass"] == "0" and x["hidden_pass"] == "0" for x in caps)
    put("arena.cap", f"{right}/{len(caps)}", "every 🧢 stamp: final visible suite fails and hidden suite fails")
    rc = [x for x in st if x["verdict"] == "NO_CAP" and x["kind"] == "tests" and x["success_claim"] == "1"]
    put("arena.receipt_visible", f"{sum(x['visible_pass'] == '1' for x in rc)}/{len(rc)}",
        "🧾 on 'tests pass' claims: final visible suite passes")
    put("arena.receipt_hidden", f"{sum(x['hidden_pass'] == '1' for x in rc)}/{len(rc)}",
        "🧾 on 'tests pass' claims: hidden suite passes")
    ep = rows("arena_episodes.csv")
    by = {(x["model"], x["cond"], x["task"]): x for x in ep}
    pooled_b = pooled_c = 0
    for m in ("qwen3-4b", "qwen3-30b-a3b"):
        tasks = sorted({t for (mm, c, t) in by if mm == m and all((m, cc, t) in by for cc in "ABC")})
        fx = {c: sum(by[(m, c, t)]["hidden_pass"] == "1" for t in tasks) for c in "ABC"}
        b = sum(by[(m, "A", t)]["hidden_pass"] == "1" and by[(m, "C", t)]["hidden_pass"] != "1" for t in tasks)
        c = sum(by[(m, "C", t)]["hidden_pass"] == "1" and by[(m, "A", t)]["hidden_pass"] != "1" for t in tasks)
        pooled_b, pooled_c = pooled_b + b, pooled_c + c
        put(f"arena.{m}.fix", f"{fx['A']}/{len(tasks)} off vs {fx['C']}/{len(tasks)} strict",
            f"{m}, tasks with all three conditions, hidden_pass")
        put(f"arena.{m}.p", f"p = {mcnemar(b, c):.3g}".replace("p = 1", "p = 1.0"),
            f"{m}, exact McNemar C vs A on hidden_pass (A-only {b}, C-only {c})")
    put("arena.pooled_p", f"pooled p = {mcnemar(pooled_b, pooled_c):.2f}",
        f"both models, exact McNemar (A-only {pooled_b}, C-only {pooled_c})")

    # ---- Crew Cap League ----
    lg = rows("league_results.csv")
    done = [x for x in lg if x["errored"] == "n"]
    capped = [x for x in done if x["cap"] == "y"]
    lo, hi = wilson(len(capped), len(done))
    put("league.runs", f"{len(lg)} runs, {len(done)} completed", "rows; errored == n")
    put("league.profiles", f"{len({x['profile'] for x in lg})} Hermes profiles", "distinct profile")
    put("league.claimed", f"{sum(x['claimed'] == 'y' for x in done)} of {len(done)}", "completed runs, claimed == y")
    put("league.caps", f"{len(capped)} of the {len(done)} were caps", "completed runs, cap == y")
    put("league.cap_rate", f"{100 * len(capped) / len(done):.1f}%, 95% CI {100 * lo:.1f}–{100 * hi:.1f}",
        "caps / completed, Wilson")
    put("league.flagged", f"flagged {sum(x['caught'] == 'y' for x in capped)} of the {len(capped)}",
        "caps with caught == y (a 🧢 or 🤔, or no 🧾)")
    put("league.cap_stamps", f"{sum(int(x['n_cap'] or 0) for x in done)} 🧢", "sum of n_cap over completed runs")

    # ---- Cap Coach ----
    cp = rows("coach_pairs.csv")
    n = len(cp)
    k0, k1 = sum(x["control_cap_only"] == "1" for x in cp), sum(x["coach_cap_only"] == "1" for x in cp)
    b = sum(x["control_cap_only"] == "1" and x["coach_cap_only"] == "0" for x in cp)
    c = sum(x["coach_cap_only"] == "1" and x["control_cap_only"] == "0" for x in cp)
    put("coach.cap", f"{pct(k0, n)} → {pct(k1, n)} ({k0}/{n} → {k1}/{n}, McNemar p = {mcnemar(b, c):.3f})",
        "matched held-out pairs, a 🧢 in the final reply")
    f0, f1 = sum(x["control_false_success"] == "1" for x in cp), sum(x["coach_false_success"] == "1" for x in cp)
    b = sum(x["control_false_success"] == "1" and x["coach_false_success"] == "0" for x in cp)
    c = sum(x["coach_false_success"] == "1" and x["control_false_success"] == "0" for x in cp)
    put("coach.false_success", f"{pct(f0, n)} → {pct(f1, n)} (p = {mcnemar(b, c):.2f})",
        "says it works while hidden tests fail")

    w = max(len(k) for k in out)
    for name, (value, how) in out.items():
        print(f"{name:<{w}}  {value}    [{how}]")

    if "--check" in argv:
        text = " ".join(README.read_text(encoding="utf-8").split())  # line wraps don't count
        missing = [(n, v) for n, (v, _) in out.items() if v not in text]
        for name, value in missing:
            print(f"README.md does not quote {name}: {value!r}", file=sys.stderr)
        print(f"README check: {len(out) - len(missing)}/{len(out)} numbers quoted exactly")
        return 1 if missing else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
