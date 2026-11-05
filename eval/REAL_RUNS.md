# Real agent runs: 🧢 precision

The synthetic set (`eval/cases.py`) overfit. On real public agent runs, version 4c572af scored a 🧢
precision of 2/60 (0.03). This file covers the re-tune. It holds aggregate numbers only. No model
output is copied here, because the dataset licence does not allow relicensing.

## Data and method

- **Dataset:** SWE-rebench trajectories (Jul 2026). 80 shards, 16 participants, 8,880 runs, with
  raw tool calls, raw outputs and final replies. Junie was excluded because its tool outputs are
  summaries, not raw output.
- **Adapter:** a small converter (not part of this repo) that feeds each trajectory's tool calls and final reply
  to the working tree. One trajectory is treated as one Hermes turn.
- **Split:** by `sha1(trajectory_id) % 2`, giving dev (even) and holdout (odd).
- **Labels:** one labeller (the agent), with no second rater. A 🧢 counts as correct only if the tool
  outputs really contradict the claim.
- **Unacknowledged failures count as contradictions.** A run that deselects or ignores a failing test
  and is then followed by "All tests pass." is labelled correct; a second labeller made the same call on
  one such case. Pre-existing failures that the reply doesn't mention are labelled correct for the same
  reason.

## Results

| step | code | split | 🧢 correct / flagged | precision | 95% Wilson CI |
|---|---|---|---|---|---|
| baseline | 4c572af | all | 2 / 60 (sample of 596) | 0.033 | 0.009–0.114 |
| dev round 1 (tuning) | e5fcc87 | dev | 6 / 27 | 0.222 | — |
| **blind holdout** | cfd2b7e | holdout | **11 / 21** | **0.524** | 0.324–0.717 |
| after round 2 (holdout seen) | 6d7b08f | holdout | 11 / 11 | 1.000 | 0.741–1.000 |
| after round 2 | 6d7b08f | dev | 6 / 6 | 1.000 | 0.610–1.000 |
| after round 2 | 6d7b08f | all labelled | 17 / 17 | 1.000 | 0.816–1.000 |

**The holdout is no longer blind.** Its failure modes drove round 2, so the 11/11 figure is a tuned
number. The honest blind figure is the 0.524 measured at cfd2b7e. To get a new blind number, a fresh
sample has to be labelled, ideally by a second rater.

**Recall.** Every one of the 11 correct holdout 🧢s at cfd2b7e is still a 🧢 at 6d7b08f, and no new,
unlabelled 🧢 appeared. Round 2 removed only wrong 🧢s.

**Volume.** 🧢s across all 8,880 runs fell from 596 at 4c572af to 17 at 6d7b08f. All 17 are bare
"All tests pass." claims (or close variants) made against a parsed failure count.

## Claim types with 🧢 switched off

These did not reach 0.9, so they never stamp 🧢. A contradiction for them is reported as 🤔 with the
disagreeing output quoted (`DISABLED_CAP` in `nocap/verdict.py`).

| kind | evidence | reason |
|---|---|---|
| `file` | dev 0/3 | Failed writes were redone another way: sed, heredocs, editor pseudo-commands |
| `build` | holdout 0/2 | Chained commands (`build && test`) and edit pseudo-commands made the exit code unreliable |

Only `tests` remains among the kinds that produced a 🧢 on real runs. Other kinds still stamp 🧢 on a
direct contradiction: `ci` (failing checks), `merged` (PR still OPEN), `pushed` (rejected push),
`committed` (failed commit) and `sha` (HEAD differs). None of them produced a 🧢 on this dataset,
because SWE-rebench runs don't push, merge or use CI. Their precision on real runs is therefore
**unmeasured**. They are covered only by the red-team and synthetic tests.

## 🤔 NO RECEIPT

A second labeller's 120 labels were matched to the current verdicts (matched on trajectory and claim text):

- 56 of the labelled claims now get 🤔.
- 24 of those are definitely wrong: the outputs prove the claim, or it isn't a claim.
- 3 are definitely right.
- 29 can't be decided from these labels. Those labels judged contradiction, not proof.

**🤔 precision is low (between 3/56 and 32/56) and is not at 0.9.** 🤔 is the abstain verdict and
never accuses, but a wrong 🤔 is still noise. The main remaining causes:

- subset-strictness on scoped claims
- runners whose summaries aren't parsed
- local lint/typecheck "checks" claims
- edits after the run

## Failure modes fixed (dev round 1 + holdout round 2)

| mode | example shape (synthetic) |
|---|---|
| narrowed claim judged against another run | "`tests/foo/` pass", "the SSH remote suite passed", "the test now passes" |
| compile claim read as a test pass | "Test sources compile successfully", "Test compilation passed" |
| failures admitted nearby | "The 2 failures are pre-existing. All 412 tests pass." |
| count equals the passes of a failing run | "All 412 tests pass." against 2 failed / 412 passed |
| N/M ratio | "412/414 pass" |
| errors-only run (setup problem) | 28 errors, 0 passed |
| exit code with no parsed counts | `pytest -x` exit 1 with no summary |
| heredoc body read as a runner | `cat > repro.py << EOF … from unittest …` |
| checklist label widening the scope | "**Ran existing tests:** the full `x` suite passes" |
| hedges | "pass functionally", "all tests that can pass are passing" |

Synthetic regressions for every mode are in `tests/test_real_runs.py`.
