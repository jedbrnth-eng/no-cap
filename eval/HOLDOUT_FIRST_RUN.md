# Holdout, first and only blind run

Code frozen at commit 8049f29 (the commit that added the eval). Command:
`env -u PYTHONPATH .venv/bin/python eval/run_eval.py --split holdout --show`

| metric | precision | recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| claim found | 0.935 | 0.967 | 0.951 | 29 | 2 | 1 |
| flagged (🧢 or 🤔) | 0.800 | 1.000 | 0.889 | 12 | 3 | 0 |
| 🧢 CAP only | 1.000 | 1.000 | 1.000 | 7 | 0 | 0 |

Verdict agreement on matched claims: 28/29 (0.966)

Misses: h17 (`3.2 seconds` vs `3.2s` in output), h22/h23 (`Commit <sha> is on main` read as a
"committed" claim), h28 (`3 new test files` not read as a count; proof is three write calls).
These were fixed afterwards, so later holdout numbers are no longer blind.
