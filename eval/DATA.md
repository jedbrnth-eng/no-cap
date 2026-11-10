# Eval data and recompute

Every eval number in the [README](../README.md) is rebuilt from the files in [`data/`](data/) by one standard-library
script:

```sh
python eval/recompute.py            # every number, with how it was computed
python eval/recompute.py --check    # and check that README.md quotes each one exactly (CI runs this)
```

Wilson 95% intervals and exact two-sided McNemar tests are computed in the script itself (no SciPy).

## What is here, and what is not

| File | Rows | What it holds | Source run |
|---|---|---|---|
| [`data/blind3_items.csv`](data/blind3_items.csv) | 180 | Blind round 3 at `01a1fab`: one row per rated item | [BLIND3.md](../docs/eval/BLIND3.md) |
| [`data/blind2_items.csv`](data/blind2_items.csv) | 177 | Blind round 2 at `7c6cbc0`, plus each item's verdict re-scored at `c5cbad1` | [README_METHOD.md](README_METHOD.md) |
| [`data/arena_episodes.csv`](data/arena_episodes.csv) | 139 | No Cap Arena: one row per episode (model, condition, task, visible/hidden pass, claimed success, cap, stamp counts) | [ARENA.md](../docs/eval/ARENA.md) |
| [`data/arena_stamps.csv`](data/arena_stamps.csv) | 119 | Every No Cap stamp in the annotate (B) and strict (C) episodes, with the episode's final visible/hidden result | same |
| [`data/arena_claim_labels.csv`](data/arena_claim_labels.csv) | 81 | The hand labels for "claimed success" on hidden-fail episodes (one rater) | same |
| [`arena-suite/`](arena-suite/) | 30 tasks | The Arena task suite (MIT): buggy repo, visible tests, hidden tests, reference fix, grader | same |
| [`data/league_results.csv`](data/league_results.csv) | 227 | Crew Cap League: one row per run (profile, model, task, claimed, hidden pass, cap, caught, stamp counts) | [LEAGUE.md](../docs/eval/LEAGUE.md) |
| [`data/league_summary.json`](data/league_summary.json) | | League aggregates per profile, family, route and overall | same |
| [`data/coach_pairs.csv`](data/coach_pairs.csv) | 39 | Cap Coach: one row per matched held-out pair (control vs coach rules) | [COACH.md](../docs/eval/COACH.md) |
| [`data/coach_mining.csv`](data/coach_mining.csv) | 30 | Cap Coach: the mining-set episodes (no rules) | same |

**Blind rounds: ids, hashes and labels only.** The runs come from the public SWE-rebench dataset
[`ibragim-bad/swe_rebench_07_2026_trajectories`](https://huggingface.co/datasets/ibragim-bad/swe_rebench_07_2026_trajectories).
Its licence leaves the trajectories under their providers' terms, so no trajectory text, claim text or rater reason
is copied here. Each row has what you need to find and check the item yourself:

| Column | Meaning |
|---|---|
| `trajectory_id`, `participant`, `run` | the dataset's own ids |
| `shard`, `shard_content_sha256` | the dataset file the run is in, and that file's `content_sha256` from the dataset's `index.jsonl` |
| `row_sha256` | SHA-256 of the run's JSON line, exactly as stored in the decompressed shard |
| `claim_idx`, `claim_sha256` | which claim No Cap extracted from the final reply (0-based), and SHA-256 of its UTF-8 text (empty for `UNSTAMPED` items, whose unit is the whole reply) |
| `stratum`, `nocap_verdict`, `kind` | how the item was sampled and what No Cap said at the round's commit |
| `rater_claude`, `rater_gemini` | both raters' labels from the verdict-free packets (PROVEN / UNPROVEN / CONTRADICTED / NOT_A_CLAIM) |
| `agreed_pre_audit`, `final` | the agreed label before the raw-run audit, and the adjudicated label every number uses |
| `error_class` (round 3) | the class of each wrong 🧾 and each miss, as listed in BLIND3.md |
| `rescore_c5cbad1_verdict`, `rescore_c5cbad1_shown` (round 2) | the same claim re-judged at `c5cbad1` (tuned on this sample, so not blind) |

To check an item: download the shard, confirm its hash, find the line whose `trajectory_id` matches and hash it, then
run No Cap at the round's commit over that run (the adapter maps one trajectory to one Hermes turn; see
[README_METHOD.md](README_METHOD.md)). The rater prompts are not published.

**Arena, League and Coach: our own synthetic tasks.** The tasks were written for this project (MIT). The League's 10
tasks are the Arena tasks of the same names, unchanged. Cap Coach used the same suite, except that its copy of
`t04_js_slow_chunk/repo/chunk.mjs` lacked one line (`if (size < 1) return [];`). The League rows name the Hermes profile
and model of each run; session ids are dropped and no session text is included. Claim text in `arena_stamps.csv` is
what the local Qwen3 models wrote about these synthetic tasks.

The one real-model episode shown as footage in the README is copied in full in
[`docs/media/real-catch/episode/`](../docs/media/real-catch/episode/) (its prompt, event stream, receipts and record).
