# Blind real-run sample, round 3 (`01a1fab`)

A third blind evaluation on a fresh sample of public SWE-rebench agent runs that no earlier round, label file or test
had seen. No claim text or run text is copied here; the run ids, row hashes, both raters' labels and the adjudicated
label of every item are in [eval/data/blind3_items.csv](../../eval/data/blind3_items.csv) (columns:
[eval/DATA.md](../../eval/DATA.md)), and `python eval/recompute.py` rebuilds the numbers below.

**Quote this:** 🧾 precision 0.92 (92/100, 95% CI 0.85–0.96) on a fresh blind sample of public SWE-rebench runs at
01a1fab, two raters (Claude, Gemini 3.8 Flash; kappa 0.66), adjudicated. No 🧢 appeared on unseen runs in round 3, so
🧢 wasn't measured. The latest blind 🧢 figure stays round 2's: 8 of 11 at 7c6cbc0 (🧾 0.88, 88/100 there).

## Results

At `01a1fab` the default `show_uncertain` level is `off`, so the only stamps users see by default are 🧾 and 🧢.

| stamp | n | precision (adjudicated) | 95% Wilson CI | sampling |
|---|---|---|---|---|
| 🧾 receipt | 100 | **0.92** (92/100) | 0.85–0.96 | seeded draw from 3,078 visible 🧾 on unseen runs, one per run |
| 🧢 cap | 0 | not measured | none | census: the unseen pool has no visible 🧢; all 12 🧢 at `01a1fab` fall on runs used by earlier rounds |
| 🤔 at the default (`off`) | 0 | not measured | none | 🤔 is not shown at the default |
| 🤔 at `show_uncertain=expected` (opt-in) | 20 | 0.15 (3/20) | 0.05–0.36 | seeded draw from 350 opt-in-visible 🤔 on unseen runs |

**Misses.** 60 unstamped replies containing a completion phrase, drawn by seed, one per run:

- 23 of 60 (**0.38**, 95% CI 0.27–0.51) carried an unsupported checkable claim with no stamp.
- 1 of 60 (0.02) was a missed 🧢: a contradicted claim, written as checklist lines that were never parsed as claims.
- 32 of 60 had every claim proven; 5 of 60 had no checkable claim.

By class, the 23 unsupported misses are:

| class | count |
|---|---|
| unscoped "all tests pass" after only a subset run (No Cap extracts it as a 🤔, visible only at `all`) | 9 |
| claimed reproduction, verification or count not shown | 5 |
| stale: the proving run predates a later edit | 4 |
| "pre-existing failure" without a base check | 2 |
| other | 2 |
| contradicted (the missed 🧢) | 1 |

**Where 🧾 goes wrong (8 of 100).** 7 are stale receipts: the cited run was green, then the agent edited code or a test
and claimed final-state success without re-running. 1 is a count/scope overclaim that the run contradicts (a hidden
🧢, 1 of 100). File claims were 27 of 27 right; test claims 61 of 68 (0.90).

**Opt-in 🤔 (`expected`).** 17 of 20 were wrong. In 15 of them the claim was proven in the run (stash baselines,
prior-failure repros, golden diffs, full builds) while No Cap said nothing relevant ran. This is why 🤔 stays off by default.

**Inter-rater agreement** (both raters on packets, before adjudication): n = 180, raw agreement 0.83, Cohen's κ = 0.66
(4 labels); 0.71 for PROVEN / UNSUPPORTED / NOT_A_CLAIM.

## Compared with round 2 (`7c6cbc0`)

| measure | round 2 | round 3 |
|---|---|---|
| 🧾 precision | 0.88 (88/100), CI 0.80–0.93 | 0.92 (92/100), CI 0.85–0.96 |
| 🧢 precision | 8 of 11 | not measured (0 on unseen runs) |
| miss rate (unstamped, unsupported) | 0.23 (14/60) | 0.38 (23/60) |
| missed 🧢 | 0 of 60 | 1 of 60 |
| κ, Claude vs Gemini | 0.77 (Gemini 4 Argon) | 0.66 (Gemini 3.8 Flash) |

The 🧾 rise is within overlapping intervals, so it is not a demonstrated improvement. The miss rate is worse on the
point estimate, also with overlapping intervals, so it is not a demonstrated regression either.

## Sensitivity

| variant | 🧾 | miss rate |
|---|---|---|
| reported (judgement calls resolved against No Cap) | 0.92 | 0.38 |
| judgement calls flipped | 0.93 | 0.38 |
| no raw-run audit of agreed labels | 0.87 (CI 0.79–0.92) | 0.53 |
| Claude's packet labels alone | 0.86 | 0.57 |
| Gemini's packet labels alone | 0.84 | 0.63 |

Do not quote a 🧾 number above 0.92. The conservative reading without the audit is 0.87.

## Method

1. **Freeze.** The commit under test, `01a1fab`, was run from a read-only clone with HEAD verified.
2. **Judge.** No Cap ran over all 8,880 runs in the dataset index (8,130 claims, 0 errors), recording visibility at
   `off`, `strict` and `expected`.
3. **Exclusions.** 626 run ids used by any earlier round, label file or development set were excluded, leaving 8,254
   unseen runs. A contamination check found none of the sampled run ids in any label, test, eval or doc file.
4. **Sample.** Seeded draw (seed 20261108), at most one item per run per stratum: 100 visible 🧾, 60 unstamped
   completion-phrase replies (the same regex as rounds 1 and 2), and 20 🤔 visible only at `expected`. 180 items on
   180 distinct runs across 16 participants, shuffled.
5. **Packets.** Evidence packets were built from dataset events only, with No Cap's verdict, reason, quote and cite
   removed. The rubric is unchanged from rounds 1 and 2.
6. **Raters.** Claude labelled all 180 packets before seeing any Gemini output. Gemini 3.8 Flash (High) labelled the
   same packets in batches of 10 (the Gemini 4 Argon quota used in round 2 was spent).
7. **Adjudication.** All 30 disagreements were resolved against the full raw run, each with a written reason. 40 agreed
   UNPROVEN or CONTRADICTED labels were also audited against the raw run (16 flipped to PROVEN). Agreed
   PROVEN labels were checked by a scan for failure lines after the last edit (31 hits, each reviewed; none flipped).

## Limits

- **No 🧢 in the unseen pool.** The blind 🧢 precision of `01a1fab` is unknown. A new 🧢 number needs new runs.
- **Packets cut evidence.** 16 agreed labels were overturned on the raw runs; packet-only labels understate No Cap.
- **Weaker second rater** than round 2 (κ 0.66 against 0.77).
- **The agreed-PROVEN audit is a scan**, not a line-by-line re-read.
- **One adjudicator**, who was also rater 1. Written rules (staleness, number scoping) were applied the same way across
  items, and borderline calls went against No Cap.
