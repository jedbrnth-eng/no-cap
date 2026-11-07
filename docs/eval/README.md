# No Cap evaluations

Every number in the README comes from one of these. Each page gives the method, the aggregate counts and the limits.
The per-item data behind them is in [eval/data/](../../eval/data/), and `python eval/recompute.py` rebuilds every
README number from it ([eval/DATA.md](../../eval/DATA.md)). The blind rounds publish public run ids, hashes and
labels, no trajectory text; the Arena, League and Coach tasks are original synthetic ones written for this project
([eval/arena-suite/](../../eval/arena-suite/), MIT). No private session text is published.

| Eval | What it measures | Headline | Page |
|---|---|---|---|
| Blind real-run sample, round 3 | Are the stamps right on unseen public SWE-rebench runs at 01a1fab? Two raters, adjudicated | 🧾 0.92 (92/100); no 🧢 on unseen runs, so not measured; 23 of 60 unstamped completions unsupported | [BLIND3.md](BLIND3.md) |
| Blind real-run sample, round 2 | The same at 7c6cbc0 (latest blind 🧢 figure) | 🧾 0.88 (88/100), 🧢 8 of 11 | [eval/README_METHOD.md](../../eval/README_METHOD.md) |
| Crew Cap League | Who says "fixed" when hidden tests fail? 25 Hermes profiles × 10 tasks | 10 caps in 209 completed runs; No Cap flagged 1 of 10 | [LEAGUE.md](LEAGUE.md) |
| No Cap Arena | Does No Cap change the real fix rate? Off / annotate / strict, 2 local models | 🧢 13 of 13 right; strict did not raise the fix rate | [ARENA.md](ARENA.md) |
| Cap Coach proof | Do approved coach rules change anything on held-out tasks? | 🧢 18% → 0% (p = 0.016); hidden false-success not significant | [COACH.md](COACH.md) |
| Synthetic battery | Precision/recall on 113 bundled lie/truth cases (many used in tuning) | run `hermes nocap battery` | built in |

Charts: [crew_leaderboard.png](crew_leaderboard.png) / [.svg](crew_leaderboard.svg),
[arena_fix_rate.png](arena_fix_rate.png) / [.svg](arena_fix_rate.svg),
[cap-coach-before-after.png](../media/coach-proof/cap-coach-before-after.png) / [.svg](../media/coach-proof/cap-coach-before-after.svg).
