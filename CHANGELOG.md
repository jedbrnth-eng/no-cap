# Changelog

Versions follow `plugin.yaml`. Entries are the merged pull requests to
[jedbrnth-eng/no-cap](https://github.com/jedbrnth-eng/no-cap/pulls?q=is%3Apr+is%3Amerged), by PR number
(`gh pr list -R jedbrnth-eng/no-cap --state merged`).

## 0.2.1

- Security (judge review S1, S2, S3, S11, S12). S1: a RECEIPT-SHAPED line (a stamp, a quoted claim, then `call N`,
  `turn N` or `→`) counts as forged wherever it sits (blockquote, quotation marks, list, code span, fence), closing
  the blockquote hole from the dogfood round; only a legend or a stamp without a quoted claim stays exempt. A reply
  that holds any stamp-like text while No Cap issued none ends with "No Cap issued no stamps for this reply". S2: on a
  non-local platform (a gateway chat, or an empty platform) `/nocap` and `/nocap verdict` show only this chat's
  receipts (no fallback to another session), print no store path, and the `/capscore board` Hall of Cap lists only
  this chat's caps. S3: the `/cap` steer and the strict `pre_verify` message give parsed counts ("3 failed, 41 passed
  (exit 1)"), never the matched output line, and quote the agent's claim as labelled data (capped, with `[ ] < >`,
  quotes, backticks and newlines removed). S11: a reply ending inside an open fence, `<!--` or `<details>` gets it
  closed before the footer. S12: `/nocap purge` and `/cap coach approve|revert|--apply` are refused from non-local
  platforms. Tests: `tests/test_judge_review_fixes.py`.
- Suite tampering (the Lie Ladder's rung 6): deleting, moving, skipping or deselecting tests, conftest collection
  hooks, runner-config filters and `PYTEST_ADDOPTS=-k …` env filters are recorded per call (any tool, including
  `write_file` content and `sed -i`). A green run after such a change no longer earns 🧾 for "all tests pass": it gets a
  visible 🤔 naming the change, and 🧢 "the failing test was removed, not fixed" when an earlier run named that test as
  failing ([docs/SUITE_TAMPER.md](docs/SUITE_TAMPER.md)). A test runner script or Makefile the agent wrote this session
  caps its 🧾 at 🤔.
- `/cap` re-checks prove the session's work, not mere existence: "created X" needs a write in the session ledger or an
  mtime after the session started; "pushed" needs a push in the ledger or an "update by push" reflog entry after the
  session started; a SHA must be on HEAD and shown in the session or committed after it started.
- Redaction: `curl -u user:pw`, `mysql -pPW`, `sshpass -p`, `redis-cli -a`, `--pass`/`--passwd`/`--passphrase` flags;
  the home directory becomes `~` in stored and printed commands and working dirs. Pytest node ids (`test_auth.py::x`)
  are no longer masked as `name: value` secrets.
- Lie Ladder: rung 6 (the skipped test), recorded at the shipped default settings; the page says which rungs are
  stamped at defaults. The demo shell gets a minimal environment and hash-pinned dependencies.

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
- Redaction: a private key behind a secret-looking name (`private_key: -----BEGIN ...`, `TLS_KEY=...`) is masked
  whole; the KEY=value rule used to take only the `-----BEGIN` word and leave the key body. The CLI-password and
  URL-password rules are skipped by a plain substring test when their literal word (`curl`, `mysql`, `sshpass`,
  `--pass`, `://`) is absent, and the KEY=value and `token <v>` rules when the text holds no secret word at all, so
  masking 100 KB of ordinary output is faster than in 0.2.0 despite the new rules. A differential test holds the
  gated rules equal to the ungated ones (`tests/test_redaction.py`).
- A claim that all tests pass with a failure word beside it ("All tests pass despite the failed run.") no longer gets
  🧾 from a failing run (it read as "says the tests fail", which the run then proved), is not counted as a retraction
  by the /cap re-score, and is still mined by Cap Coach. "Some tests pass, others fail" is unchanged
  (`tests/test_final_dogfood.py`).
- Redaction: stored summary lines (test summary, push, commit, merge and CI lines) are masked whole before they are cut
  to 160 characters. They were cut first, so a long URL password lost its closing `@` and its first characters were
  stored and could be quoted in a receipt. The same for the test command's suite name and a claim's own text; and
  the head, middle and tail windows of a long tool output now end on a line or word boundary, never inside a token
  (`tests/test_redaction.py`).
- Licence: Apache-2.0 from 0.2.1 (was MIT), with a NOTICE file. The Arena task suite stays MIT.

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
