# Changelog

Versions follow `plugin.yaml`. Entries are the merged pull requests to
[jedbrnth-eng/no-cap](https://github.com/jedbrnth-eng/no-cap/pulls?q=is%3Apr+is%3Amerged), by PR number
(`gh pr list -R jedbrnth-eng/no-cap --state merged`).

## 0.2.0 (2026-11-06)

Engine and receipts
- Stop false receipts: former failures now passing, single-file runs, honest failure reports ([#9](https://github.com/jedbrnth-eng/no-cap/pull/9))
- Engine: cross-turn receipts, fabricated-artifact detector, Chinese/Thai/Spanish claims, `nocap battery` ([#6](https://github.com/jedbrnth-eng/no-cap/pull/6))
- CPU-time ReDoS budget test; README install from GitHub ([#1](https://github.com/jedbrnth-eng/no-cap/pull/1))

New surfaces and commands
- Cap Coach: mine what an agent caps on, approved fixes, held-out before/after ([#8](https://github.com/jedbrnth-eng/no-cap/pull/8))
- Lie Ladder demo theater, `/nocap verdict` card, `/capscore compare` A/B, export + metrics ([#7](https://github.com/jedbrnth-eng/no-cap/pull/7))
- Discord-native receipts: split-proof footer, opt-in embed + Call cap / Show receipts buttons ([#5](https://github.com/jedbrnth-eng/no-cap/pull/5))
- Cap Board: dashboard leaderboard of the top cappers per agent, model and skill ([#3](https://github.com/jedbrnth-eng/no-cap/pull/3))
- Hermes Desktop: clickable receipt chips (signed, Desktop-only, off until the desktop half is on) ([#2](https://github.com/jedbrnth-eng/no-cap/pull/2))

Security and project
- Security CI (tests, ReDoS budget, gitleaks, bandit) and SECURITY.md ([#4](https://github.com/jedbrnth-eng/no-cap/pull/4))
- One version everywhere: `plugin.yaml`, `__version__` and the dashboard manifest are 0.2.0 (the manifest already
  said 0.2.0 while `plugin.yaml` said 0.1.0); `tests/test_version.py` keeps them and this file in step.
- README hero with the League, Arena and Coach charts; eval summaries in [docs/eval/](docs/eval/).

## 0.1.0 (2026-11-05)

- First release (`cbe89d5`): the `post_tool_call` ledger and `transform_llm_output` receipt footer (🧾 NO CAP /
  🧢 CAP / 🤔 NO RECEIPT), `/cap`, `/capscore`, strict mode with `pre_verify`, `/nocap doctor` and `purge`.
