# How No Cap was evaluated

Aggregate numbers only. No dataset text is in this repository: no replies, commands or tool output from the
evaluated runs. Every test fixture is synthetic (made-up project names, paths and counts); a 40-character
substring check of every string in the repo against the dataset finds only tool-format boilerplate (pytest and
cargo summary lines, git diffstat, compiler error formats) and common code idioms, no agent-written text and no
agent commands.

## Data

- **Runs:** public SWE-rebench agent trajectories (July 2026 release, `ibragim-bad/swe_rebench_07_2026_trajectories`
  on Hugging Face), several coding agents and models. Each trajectory has the agent's raw tool calls, their raw
  output and the final reply.
- **Licence:** the dataset card says third-party content keeps its own licences and the dataset does not relicense
  it. That is why only measured numbers are published here.
- **Unit:** one trajectory is treated as one Hermes turn. A small converter (not part of this repo) feeds its tool
  calls to the `post_tool_call` path and its final reply to the `transform_llm_output` path of a given commit.

## Blind evaluation (the number in the README)

- **Code:** frozen at `7c6cbc0` before the sample was drawn.
- **Sample:** a fresh sample of completion replies, separate from the runs used in the earlier rounds below.
- **Raters:** two independent model raters, Claude and Gemini, each labelling every claim PROVEN, CONTRADICTED or
  UNPROVEN from that run's own tool outputs. Agreement: Cohen's kappa 0.77. Disagreements were adjudicated, and
  the adjudicated label is the one scored.
- **Scores:** 🧾 precision = share of 🧾 stamps whose claim is PROVEN; 🧢 precision = share of 🧢 stamps whose
  claim is CONTRADICTED; 95% intervals are Wilson intervals.

| result at `7c6cbc0` | value |
|---|---|
| 🧾 precision | 0.88 (88/100, 95% CI 0.80-0.93) |
| 🧢 correct | 8 of 11 |
| unstamped completion replies with an unsupported claim | about 1 in 4 |

### Error classes (counts)

🧾 wrong, 12 of 100:

| class | count |
|---|---|
| stale receipt: code edited after the only proving run | 5 |
| "all tests" claim backed only by a subset run | 3 |
| not a claim of that type (a pattern read as a file, an issue's error read as a number) | 2 |
| a failing test deselected before the green run, not admitted | 1 |
| a failure admitted elsewhere in the reply | 1 |

🧢 wrong, 3 of 11: the failure was admitted later in the same reply (2); the claim was scoped by a colon to a list
that was all green (1). The 8 correct 🧢 were all unadmitted "all tests pass" claims after a failing full-suite run.

🤔 at the `strict` level: 0 of 6 visible 🤔 were right. All six claims were proven by the run, mostly by the
agent's own check script or smoke test, which No Cap did not count as evidence.

Unstamped misses (unproven claims left quiet): stale or never re-run, unscoped "all tests", reproduction or
process claims with no visible run, counts not shown. None of the misses was a contradicted claim.

### What changed after it

Each error class above got synthetic regression tests (`tests/test_blind2_classes.py`) and a fix: the whole reply
is read for admissions before 🧢 or an "all pass" 🧾; "All tests pass:" + a list is scoped to the list; count
claims need a run after the last code edit, and `patch`/`perl -pi` count as edits; a skip marker added after a
failure blocks the receipt; "all existing tests" needs a full run; check scripts count as test-like evidence.
Visible 🤔 is now off by default, because the `strict` fix has no fresh blind sample behind it.

The release commit was re-scored on the same labelled sample (tuned, not blind; a new blind number needs a new
sample): 🧢 8/8 visible stamps correct (the 3 wrong 🧢 now abstain, the 8 correct ones are kept); 🧾 86/96 = 0.896
(95% CI 0.82-0.94; 4 earlier 🧾 now abstain); no visible 🤔. Across all runs in the dataset, visible 🧢 went from
16 to 12 and visible 🧾 from 3,668 to 3,571.

Adjudication note: disagreements were settled by the Claude rater against the raw run, so the adjudicator is not
a third independent rater. Every flip has a written reason.

## Earlier rounds

- First blind evaluation, at `2e902e5`: 🧾 precision 0.895 (51/57, 95% CI 0.79-0.95), two raters, kappa 0.76.
  Its sample had no 🧢. Its error classes are covered by `tests/test_blind_classes.py`.
- Single-labeller tuning rounds on a dev/holdout split: [REAL_RUNS.md](REAL_RUNS.md). The holdout there is no longer
  blind.
- The synthetic labelled set: `eval/cases.py`, scored by `eval/run_eval.py`
  ([HOLDOUT_FIRST_RUN.md](HOLDOUT_FIRST_RUN.md) is its only blind run).
