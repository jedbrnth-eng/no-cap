# No Cap Arena: method and aggregate results

Does No Cap change what an agent really gets done? The same agent ran 30 bug-fix tasks three times: with No Cap
off (A), in annotate mode (B, stamps only) and in strict mode (C, stamps plus `pre_verify` nudges). "Really fixed"
means hidden tests the agent never saw pass.

Run 2026-11-05, No Cap at `aa69dcb`, Hermes v0.22.5+2362.g8acb7f6.

![No Cap Arena chart](arena_fix_rate.png)

<sub>Paired tasks only (all three conditions finished). SVG: [arena_fix_rate.svg](arena_fix_rate.svg). Per-episode and
per-stamp rows: [eval/data/arena_episodes.csv](../../eval/data/arena_episodes.csv),
[eval/data/arena_stamps.csv](../../eval/data/arena_stamps.csv); `python eval/recompute.py` rebuilds the headline.</sub>

## Headline

- **Strict mode did not raise the fix rate.** Exact McNemar, really fixed, C vs A: qwen3-4b A-only 4 / C-only 1,
  p = 0.375; qwen3-30b-a3b A-only 1 / C-only 0, p = 1.0; pooled (46 pairs) A-only 5 / C-only 1, p = 0.22. The point
  estimates are lower under C; none of the differences is significant. Cap rate C vs A, pooled: A-only 5 / C-only 7,
  p = 0.77.
- **🧢 was right every time: 13 of 13 stamps**, each checked by hand. Each cited a test run with failures (exit 1),
  the final visible suite failed, and the hidden suite failed too. No false 🧢.
- **🧾 is a receipt for the run, not for the fix.** 50 🧾 stamps on "tests pass": the visible suite really passed in
  50 of 50, but the hidden tests passed in only **33 of 50 (66%)**.
- 1 wrong 🧾 (a P0 bug, fixed in [#9](https://github.com/jedbrnth-eng/no-cap/pull/9)): "All three failing tests now pass." stamped 🧾 on a `3 failed, 4 passed` run.

## Results

| model | cond | n | really fixed (hidden pass) | claimed success | cap rate | strict-nudged episodes |
|---|---|---|---|---|---|---|
| qwen3-4b | A off | 30 | 10/30 = 33% [19–51] | 23/30 | 14/30 = 47% [30–64] | 0 |
| qwen3-4b | B annotate | 30 | 8/30 = 27% [14–44] | 21/30 | 13/30 = 43% [27–61] | 0 |
| qwen3-4b | C strict | 30 | 7/30 = 23% [12–41] | 21/30 | 15/30 = 50% [33–67] | 6 |
| qwen3-30b-a3b (partial) | A off | 16 | 11/16 = 69% [44–86] | 16/16 | 5/16 = 31% [14–56] | 0 |
| qwen3-30b-a3b (partial) | B annotate | 17 | 12/17 = 71% [47–87] | 17/17 | 5/17 = 29% [13–53] | 0 |
| qwen3-30b-a3b (partial) | C strict | 16 | 10/16 = 62% [39–82] | 16/16 | 6/16 = 38% [18–61] | 2 |

The 30B run stopped after 49 of 90 episodes (the Mac ran out of memory): 16 tasks with all three conditions plus 1
lone B episode. The chart and the paired tests use the 16 complete triples only (B = 11/16 there).

Of the 39 caps in B and C: 13 got 🧢, 9 got 🤔 or no stamp, and 17 got only 🧾 (the agent's visible tests were
green: the partial-fix traps). Strict could not fire on 8 of qwen3-4b's 15 strict caps because the turn made no file
edit. Strict cost (C − A, paired): qwen3-4b mean +46 s (median +12 s), +1.7 model calls; qwen3-30b-a3b mean −19 s
(median 0), +0.2 calls.

## Method

- **Suite.** 30 original synthetic bug-fix tasks ([eval/arena-suite/](../../eval/arena-suite/), MIT, written for this project; 26 Python, 4 JS; easy, medium, slow
  and partial-fix traps). The agent sees visible tests; hidden tests (never in its dir) define "really fixed" and run
  on a copy of the final work dir with its conftest and pytest config ignored.
- **Agent.** `hermes chat -Q --oneshot`, a throwaway `HERMES_HOME` per condition, a fresh git repo and a throwaway
  `GIT_CONFIG_GLOBAL` per episode, the same prompt in every condition. Conditions for one task run back to back in a
  rotating order (seeded), 1 rep.
- **Models.** Local llama.cpp server (0.7.0 b11669), 64K context per slot, q8 KV cache, temperature 0.7, top-p 0.8,
  top-k 20: `unsloth/Qwen3-4B-Instruct-2507-GGUF` Q4_K_M (sha256 `3605803b…c67e597`) and
  `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF` Q4_K_M (sha256 `6c997b8a…c4774d0`).
- **Claimed success.** A hand label for every hidden-fail episode, an automatic rule otherwise. Cap = claimed success
  and hidden fail. Wilson 95% CIs; exact two-sided McNemar on paired tasks.

## Limits

- 1 rep, 2 small local models, 30 synthetic tasks; the 30B run is partial (16 tasks). The CIs are wide: no difference
  is detectable at this n.
- Claim labels are one person's. Machine load from other work during the runs makes wall times noisy.
