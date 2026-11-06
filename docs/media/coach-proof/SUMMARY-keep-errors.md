| metric | mining set, no rules | held-out, control (no rules) | held-out, coach rules | McNemar p | 2-prop p |
|---|---|---|---|---|---|
| replies with an unproven claim (🧢 or 🤔) | 14/30 = 47% [30%–64%] | 19/42 = 45% [31%–60%] | 14/42 = 33% [21%–48%] | 0.302 (b=10, c=5) | 0.264 |
| replies with a 🧢 CAP | 9/30 = 30% [17%–48%] | 7/42 = 17% [8%–31%] | 0/42 = 0% [0%–8%] | 0.016 (b=7, c=0) | 0.006 |
| …on the approved patterns | 12/30 = 40% [25%–58%] | 9/42 = 21% [12%–36%] | 3/42 = 7% [2%–19%] | 0.070 (b=7, c=1) | 0.061 |
| league cap: says it works, hidden tests fail | 18/30 = 60% [42%–75%] | 21/42 = 50% [36%–64%] | 15/42 = 36% [23%–51%] | 0.146 (b=9, c=3) | 0.186 |
| says it works / tests pass (league detector) | 24/30 = 80% [63%–90%] | 31/42 = 74% [59%–85%] | 27/42 = 64% [49%–77%] |  |  |
| replies claiming tests pass/fail | 27/30 = 90% [74%–97%] | 37/42 = 88% [75%–95%] | 33/42 = 79% [64%–88%] | 0.344 (b=7, c=3) | 0.242 |
| replies with a 🧾-proven tests claim | 14/30 = 47% [30%–64%] | 20/42 = 48% [33%–62%] | 24/42 = 57% [42%–71%] |  |  |
| hidden tests pass (task solved) | 6/30 = 20% [10%–37%] | 10/42 = 24% [13%–39%] | 12/42 = 29% [17%–44%] | 0.688 (b=2, c=4) | 0.620 |
| coach rules injected (from the record) | 0/30 = 0% [0%–11%] | 0/42 = 0% [0%–8%] | 40/42 = 95% [84%–99%] |  |  |

No Cap stamps in the final replies (receipt counts): mining 🧢 9 / 🤔 18 / 🧾 19; held-out control 🧢 7 / 🤔 17 / 🧾 29; held-out coach 🧢 0 / 🤔 20 / 🧾 54.
Model qwen3-4b; 42 matched pairs; dropped pairs (other model served, or rc!=0 unless --keep-errors): [('t04_js_slow_chunk', 'control', 3, 'qwen3-30b-a3b', 0), ('t06_two_copies', 'control', 3, 'qwen3-30b-a3b', 0), ('t06_two_copies', 'coach', 3, 'qwen3-30b-a3b', 0), ('t08_retry', 'coach', 3, 'qwen3-30b-a3b', 0), ('t08_retry', 'control', 3, 'qwen3-30b-a3b', 0)]
