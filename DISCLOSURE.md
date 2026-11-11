# No Cap: disclosure

What No Cap stores, reads, runs and sends, for the catalog review and for anyone installing it. Everything here is
local to the machine Hermes runs on; there is no network use unless you turn on `self_verify_http`.

- **Output it keeps:** never the full output of a tool call; only the matched summary/error line (≤160 chars,
  masked), plus parsed facts and the filenames a command's output names (`written_in_output`), through the same
  secret masker.
- **Reply rewriting:** the reply text is never edited except to remove a forged `::nocap` directive and append the
  footer. A forged directive (any `::nocap` the model wrote, after NFKC normalisation and removal of Unicode format
  characters) is removed on every surface and counted as a forged stamp.
- **Stores:** one JSON line per checked reply in `HERMES_HOME/plugin-data/<no-cap id>/receipts.jsonl` (the exact path:
  `hermes nocap path`; folder created `0700`, file `0600`). A line holds: session id, turn id, model, platform and
  mode; per claim, its text (up to 200 characters), kind, verdict, reason and a quoted summary line (a test count or a
  push line, up to 160 characters); per tool call **that a receipt cites**, the tool name, the command (first 160
  characters), exit code, error line, and the facts parsed from it (test counts, push refs, commit line, PR numbers,
  paths written, HTTP status, the directory the command names). The other calls of the turn are stored only as a
  count and a SHA-256 digest of their tool names and argument hashes, never as commands. `/cap` adds a record with the
  same claim fields. Every text field goes through a secret masker before it is written (KEY=value pairs named like a
  secret, URL passwords, provider tokens, AWS keys, JWT/Discord tokens, PEM keys; `tests/test_redaction.py`); ids are
  stored as they are. Pruned after `retention_days` and halved past 20 MB. `/nocap purge` deletes the store and the
  scorecard.
- **Session ledger** (`cross_turn`, on by default): `ledger.jsonl` in the same folder (`0600`, folder `0700`), one line
  per checked turn: session id, turn id, turn number, and per tool call of that turn the parsed facts (tool name,
  command up to 160 characters, exit code, error line, test summary lines, git facts such as push refs, commit SHA and
  PR numbers and states, SHAs seen, paths written, and flags such as "edited code"), including the tool's own working
  directory (`workdir`, first 300 characters), so a claim about another repo isn't judged against this one. Never the
  full output; only the matched summary/error line (≤160 chars, masked); no URLs. The same secret masker (`redact()`)
  runs on every field, `workdir` included. At most 100 turns and 400 calls per session are kept (the newest), the
  same `retention_days` applies, and `/nocap purge` deletes it.
- **Test-file inventory:** a file-scoped run can count as the full suite only when its literal targets cover
  every observed test file. Only plain `pytest` / `jest` / `vitest` runs qualify (not mocha, and no flag but
  `-q`/`-v`). No Cap finds the run's project (the `.git` checkout at most four levels up, else the nearest
  `pyproject.toml`, `setup.cfg`, `setup.py`, `pytest.ini`, `tox.ini` or `package.json`) and lists it read-only, matching `test_*.py`,
  `*_test.py`, JS/TS `*.test.*` / `*.spec.*` and JS/TS files under `__tests__/`, at most four directory levels and
  2,000 visited entries. It skips `.git`, `.venv`, `venv`, `node_modules` and `__pycache__` and never follows
  symlinks. The only file contents it reads are the first 64 KB of those runner configs (and `jest`/`vitest`/`vite`
  configs) between the run's directory and the project root, to abstain when they override the test-file patterns; nothing read is stored. It abstains on errors,
  limits, an unknown working directory (never the plugin process's own), `-C`/`--repo`, or a `cd` it can't place.
  Proven full-file runs keep their redacted target filenames (at most 50) in the session ledger. The inventory adds
  no network requests, subprocesses or file writes.
- **Network:** none by default. With `self_verify_http: true`, `/cap` may send one HTTP HEAD request to a URL the
  agent claimed is live, and only to a public address: the host is resolved first and refused if any address is
  loopback, link-local (cloud metadata such as 169.254.169.254), private, carrier-grade NAT, unique-local, multicast or
  reserved (or a `.local`/`.internal` name); the request goes to the address that was checked; redirects are not
  followed; 3 s timeout. Tested in `tests/test_verify_http.py`.
- **Commands it runs:** read-only git commands as argument lists (no shell) in the session's working directory, with
  a timeout and no fetch. During `/cap`: `git cat-file -t <sha>` and `git rev-parse --verify <ref>` (5 s). At reply
  time, only when a reply claims a SHA or a branch that no tool call backs (`verify_artifacts`, at most 8 calls per
  reply, 3 s each): `git rev-parse --is-inside-work-tree --is-shallow-repository`, `git config --get-regexp` (partial
  clone check), `git cat-file -e <sha>` and `git for-each-ref refs/heads/ refs/remotes/ refs/tags/`. Every git call
  is hardened against an untrusted repo: `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `-c
  core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=never`, no pager, no lazy fetch, and a minimal
  environment: the git child inherits only `PATH`, `HOME`, `LANG`, `LC_ALL` and `SYSTEMROOT`, so provider keys and
  tokens never reach it (`tests/test_git_env.py`; `tests/test_artifacts.py` runs it against a malicious `.git/config`). It never re-runs
  tests or builds.
- **Cap Board reads:** the dashboard tab and `/capscore board` read the current profile's own store. Only with the
  `board.team_profiles` opt-in, and only in the CLI or the dashboard, they also read other profiles' stores
  (`<root>/profiles/<name>/plugin-data/…/receipts.jsonl`, opened read-only) and the `board_sources` /
  `NOCAP_BOARD_SOURCES` paths, and show those profiles' claims, cited commands and evidence lines to whoever can open
  the dashboard. A gateway chat never gets another profile's data, and within a profile `/nocap`, `/nocap verdict`
  and `/capscore board` in a gateway chat show only that chat's receipts, with no store path.
  <!-- verify-at-merge: W1 S2 behaviour -->
- **Reads outside its data:** `/cap` checks whether a file the agent says it created exists (existence and size).
  `/nocap doctor` reads other plugins' `plugin.yaml` files to find other reply rewriters, and creates and deletes one
  probe file in its own store folder.
  <!-- verify-at-merge: W2 S6 (/cap re-check needs session evidence, not mere existence) -->
- **Messages it sends:** `/cap` injects one user message (when Hermes allows it). It quotes the claims as the agent's
  own words and names only fixed read-only checks with validated arguments (`git ls-remote`, `git log -1`, `ls -l`,
  `gh pr view`, `curl -sI` to a public URL) or the plain test command parsed from an earlier run (`pytest -q`, never a
  line with `;`, `&&`, `|`, `$(`, backticks, quotes or redirects); otherwise it says "run your test suite". Strict
  mode's `pre_verify` can continue a coding turn at most twice.
  <!-- verify-at-merge: W1 S3 (steer quotes rebuilt from parsed fields, fenced claim text) -->
- **Desktop half:** `dashboard/desktop_api.py` (mounted by `dashboard/plugin_api.py`) adds three routes under
  `/api/plugins/no-cap/` on your own Hermes backend, behind the dashboard's auth: `POST /hello` writes `desktop.json`
  (on/off and a timestamp; atomic `0600` write, a fresh `O_EXCL|O_NOFOLLOW` temp file, folder tightened to `0700`) and
  returns no key; `POST /verify` answers yes/no for one chip and one chat; `GET /session?id=` reads the store for the
  Receipts list. A Desktop reply's store line also records the chip's id, signature and payload digest (hex, through
  the same redaction as every other field). No signing key is ever written; a `desktop.key` left by 0.1 is deleted.
  `/nocap purge` leaves `desktop.json`. When a Desktop reply is checked, the plugin emits the
  `plugin.no-cap.receipts.updated` event (session id only) so the list refreshes. Any authenticated dashboard caller
  (other installed dashboard or Desktop plugins included) can call these routes; they return only yes/no and this
  profile's receipts, never a key.
- **Cap Coach:** drafts and approved rules live in `coach.json` in the same folder (`0600`): pattern id, scope
  (agent profile, model, skill), counts, up to 3 redacted, truncated example claims per pattern, the rule text, and
  the frozen baseline. The rule text it injects is always No Cap's built-in text for that pattern, from its own
  library, never text read back from `coach.json` (a file the agent can write); a proposal whose pattern isn't in the
  library is never injected. Skill names are kept only if they are plain identifiers: a name with spaces, newlines or
  markup is dropped, not cleaned up, so it can't carry an instruction into a rule. Reply records also store the ids of coach rules injected that turn (coach scope reuses the
  per-turn skill names the Cap Board already records; the session's loaded skills are kept in memory only). Approved coach rules reach the model through `pre_llm_call` as
  labelled context, only in scope, never as a system-prompt edit. The only other text No Cap adds there is the fixed
  footer hint (one line, built in, no user or tool text in it; `footer_hint: off` stops it). No Cap never writes skills, memory or config; with
  `--apply` it sends one message asking the agent to make the approved skill or memory edit with its own tools.
- **Discord:** every Discord reply gets the compact Discord footer (text only). With `discord_buttons: on`, a listener
  on Hermes's discord.py client (handed over by `ctx.register_platform_handler("discord", …)`) edits **the bot's own
  reply** to add an embed and two buttons, and answers button clicks privately (ephemeral). It never reads other
  people's messages' content (it ignores any message not authored by the bot), never posts a new message, and edits
  nothing else. It stores `discord_receipts.json` next to the receipts (`0600`, atomic write, at most 500 entries,
  through the same redaction): receipt id → session id, turn id, session key, the user id the reply answered, and the
  chat and thread ids. No claim text. `/nocap purge` deletes it. 🧢 Call cap runs `/cap` (same rules as above).
- **The demo:** `demo/stub_model.py` is a scripted model on 127.0.0.1. It is test scaffolding, not part of the plugin.
  `hermes nocap demo --ladder` runs `/bin/sh demo/run_ladder.sh` (an argv list, 25-minute timeout, output in a new
  0700 temp folder unless `--out` names one; `/nocap demo ladder`
  starts the same script in the background, CLI/TUI only, never from a gateway chat). The script makes a fresh
  `HERMES_HOME` under `/tmp`, points `GIT_CONFIG_GLOBAL` at a throwaway file, installs this plugin there, starts the
  stub on the first free port in 8765-8799 on 127.0.0.1, and uses `uv` to fetch pyte, Pillow and pytest into a
  throwaway venv (that fetch is the one network use, and it is the demo's, not the plugin's).
  <!-- verify-at-merge: W2 S10 (Ladder demo minimal env, pinned deps) -->
- **Obsidian lessons bridge (off unless `obsidian_vault` is set):** writes only inside the vault you name (one
  redacted line per 🧢 in `<folder>/<profile>.md`, and Agent Black Box board notes plus `.ids` reservations), and two
  small files in this store folder (`0600`, atomic write, no claim text): `obsidian-lessons.json` (per-agent 🧢 counts
  by pattern id, with `obsidian_learn: true`; `/nocap purge` deletes it) and `obsidian-board-<dev>-<inode>.json` (the
  board notes it wrote and the next id). Nothing is read from the vault into the prompt. Details, limits and the
  residual race: `docs/OBSIDIAN.md`.
- **Cards and exports it writes:** `/nocap verdict` writes `verdict.svg`/`verdict.png` and `/capscore compare` writes
  `compare.svg`/`compare.png` in its own store folder (they quote claims and cited commands, already redacted; `/nocap
  purge` deletes them with the store). `hermes nocap export --out` and `hermes nocap metrics --file` write the file you
  name (`0600`, atomic temp file + rename; every string re-passed through the secret masker; CSV cells that start like
  a formula are prefixed with `'`). Metrics are a file in the Prometheus text format: no port, no listener.
