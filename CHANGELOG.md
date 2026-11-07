# Changelog

Versions follow `plugin.yaml`. Entries are the merged pull requests to
[jedbrnth-eng/no-cap](https://github.com/jedbrnth-eng/no-cap/pulls?q=is%3Apr+is%3Amerged), by PR number
(`gh pr list -R jedbrnth-eng/no-cap --state merged`).

## Unreleased

- Dogfood round (real 41-profile install): a stamp the reply explains or quotes (code, blockquote, quotation marks,
  a legend, "a 🧢 CAP stamp") no longer triggers the "didn't issue" warning; a stamp in receipt position still does.
  New `footer_hint` (default `auto`): one labelled `pre_llm_call` line, only when the history holds a No Cap footer,
  so models stop copying the footer Hermes replays to them. Discord footer: a claim's markdown backticks and bold are
  dropped instead of shown as `ˋ` (a command's backtick, which is content, keeps the inert `ˋ`). "…is 1a2b3c4
  (…, run in /path)." is read as a SHA claim. `/nocap doctor` shows the turns the reply hook saw and why a profile can
  have none. README limits: profiles with no completed turn, the host's `tools.override` log line.
- Security (catalog review): every git child now gets a minimal environment (`PATH`, `HOME`, `LANG`, `LC_ALL`,
  `SYSTEMROOT` plus the `GIT_*` hardening), never the agent's provider keys or tokens. Test: `tests/test_git_env.py`.
- README Disclosure now states two 0.2.0 details the catalog entry already disclosed: `ledger.jsonl` stores each
  call's working directory (`workdir`, first 300 characters, masked by `redact()`), and Cap Coach injects only its
  built-in rule text, never text from `coach.json`, keeping skill names only if they are plain identifiers.
- Docs and evidence: the README opens on a real Qwen3-4B catch (Arena e05_word_count, unedited) and is about 70%
  shorter; detail moved to [docs/GUIDE.md](docs/GUIDE.md) and [DISCLOSURE.md](DISCLOSURE.md). Stale claims fixed (CI on
  Linux, reply editing, stored output, verdict determinism, Desktop chips signed for one chat, `plugin.yaml`
  cross-turn wording). New [eval/data/](eval/DATA.md): blind rounds 2 and 3 as public SWE-rebench ids, row hashes and
  adjudicated labels; the Arena's 30-task MIT suite and per-episode/per-stamp rows; League results and summary;
  Cap Coach pairs; `python eval/recompute.py --check` rebuilds every README number (tested in CI).

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
