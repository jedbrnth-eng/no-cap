<p align="center">
  <img src="docs/banner.png" alt="No Cap: receipts for agent claims" width="860">
</p>

<h3 align="center">Your agent says “tests pass.” No Cap checks the receipts.</h3>

<p align="center">
  A Hermes Agent plugin. Each claim in the agent's final reply is checked against the tool calls it made in the same turn.<br>
  No extra model, no network, no account. The receipts stay on your disk.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-2152%20passing-2ea043" alt="2152 tests passing">
  <img src="https://img.shields.io/badge/Hermes-0.22.5%2B-7c3aed" alt="Hermes 0.22.5+">
  <img src="https://img.shields.io/badge/tested%20on-macOS-555" alt="Tested on macOS">
  <img src="https://img.shields.io/badge/network-none-2ea043" alt="No network">
  <img src="https://img.shields.io/badge/extra%20model-none-2ea043" alt="No extra model">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#more-than-a-prompt">More than a prompt</a> ·
  <a href="#commands-and-settings">Commands</a> ·
  <a href="#how-good-is-it">Eval</a> ·
  <a href="#disclosure">Disclosure</a> ·
  <a href="#known-limits-and-what-is-not-tested">Limits</a>
</p>

## Why

- **It reads the ledger, not the vibes.** A `post_tool_call` hook records every tool result in the turn: exit codes,
  parsed test counts, the ref a push really went to. Each claim in the final reply is matched against that ledger and
  stamped **🧾 NO CAP** (proven), **🧢 CAP** (contradicted) or **🤔 NO RECEIPT** (nothing ran that could prove it), with
  the call it came from.
- **It only says 🧢 when the output says the opposite.** A cap needs a direct contradiction from one parsed field (a
  failure count, a push ref, a PR state). Hedges, plans, quotes, code blocks and claims about other repos never get
  capped. Claim types that missed the precision bar on real agent runs (files, builds) can't 🧢 at all.
- **It doesn't nag.** By default only 🧾 and 🧢 are stamped. Unsure cases are recorded quietly; `/nocap all` and
  `/cap` still see them. Visible 🤔 is opt-in (`show_uncertain`): on a fresh blind sample the `strict` level's 🤔 were
  right 0 of 6 times (each claim was proven by the agent's own check script). Such scripts now count as test-like
  evidence, but that fix has not been re-measured blind, so 🤔 stays off by default.

<p align="center">
  <img src="docs/media/demo-run/01-turnA-lies.png" alt="A real Hermes CLI turn: pytest exits 1 and the push goes to feat/login, the agent replies 'All tests pass, pushed to main, and the deploy is live', and the No Cap footer shows two CAP lines citing pytest's '3 failed, 41 passed (exit 1)' and 'pushed feat/login'" width="860"><br>
  <sub>A real <code>hermes --cli</code> session in a throwaway <code>HERMES_HOME</code>, with the plugin installed by
  <code>hermes plugins install</code>. Hermes, its tools, pytest, git (a local bare origin) and No Cap are real. The model is
  not: <a href="demo/stub_model.py"><code>demo/stub_model.py</code></a> is a scripted local endpoint that plays an over-eager
  agent so the lie repeats on cue. Reproduce it with <code>sh demo/run_demo.sh</code>; every capture from that run is in
  <a href="docs/media/demo-run/">docs/media/demo-run/</a>.</sub>
</p>

> **Status: 0.1.** Submitted to the Hermes plugin catalog. Tested on macOS with Hermes 0.22.5 only.

## Install

```sh
hermes plugins install jedbrnth-eng/no-cap --enable
hermes nocap doctor          # or /nocap doctor inside a session; should end with "0 problems found."
```

Once the catalog entry is merged: `hermes plugins install no-cap`. From a clone:
`git clone https://github.com/jedbrnth-eng/no-cap && hermes plugins install "file://$PWD/no-cap" --enable`. Hooks load at session start, so restart running sessions (and the gateway)
after installing.

## How it works

| Hermes surface | What No Cap does with it |
|---|---|
| `post_tool_call` hook | Records each tool result into a per-turn ledger in memory: exit code, parsed test summary (pytest, jest, vitest, go, cargo, Gradle/Maven…), push refs, PR state, HTTP status, paths written. Raw output is never stored. |
| `transform_llm_output` hook | Finds the claims in the final reply (tests, CI, build, pushed, merged, committed, PR opened, deployed, URL live, file written, SHAs, counts), judges each against that turn's ledger, and **appends** the receipt footer. The reply text is never edited, so the classic CLI doesn't reprint it. |
| `pre_verify` hook | Strict mode only: when a coding turn is about to end with an unproven claim, the agent is told to run the check or drop the claim. At most 2 nudges per turn. |
| `/cap` | Re-checks what it can locally (read-only `git rev-parse` / `cat-file`, a file's existence for "created X"), then asks the agent to prove or retract the rest. The next reply is re-scored (🔁 lines). It never overrules a 🧢 from the turn's own output. |
| `/capscore [card]` | Per-model honesty board from the local store; `card` writes a share card (SVG, plus PNG when Pillow is there). |
| Dashboard **Cap Board** tab · `/capscore board` | The leaderboard: this profile's store by default; with the `board.team_profiles` opt-in, a team view of other Hermes profiles on this machine (found the way Hermes finds profiles, read-only, CLI and dashboard only). Ranked by cap rate per agent, model and skill, with receipt rate, streak, 7-day trend, top cap type and a Hall of Cap of the latest 🧢 with their (redacted) evidence. The tab polls every 4 s. Rates need ≥10 claims; below that the row shows n, greyed and unranked. See [docs/CAP_BOARD.md](docs/CAP_BOARD.md). |
| `/nocap verdict` | The session's receipts as a **courtroom verdict card** (SVG, plus PNG with Pillow): "In re: <model>, session <id>", numbered findings each citing its evidence (turn.call, command, exit code, quoted output), and a closing sentence computed from the counts ("0 of 5 claims proven; 2 counts of contradiction, 1 count of unverified SHA, …"). Counts always; a percentage only from 10 claims up. |
| `/capscore compare A B` | **Honesty A/B** card from the store: claims checked, cap rate with a 95% Wilson interval, receipt rate, top cap types and a per-kind breakdown, side by side. Below 10 claims a model is greyed out and never called the winner; a winner is named only when the intervals don't overlap. |
| `/nocap [all\|doctor\|purge]` | The last receipts, every receipt including unstamped ones, setup checks, delete the store. Same as `hermes nocap …` in a terminal. |
| Hermes Desktop (`desktop/plugin.js`, public Desktop plugin SDK) | The receipt lines become **clickable chips** inside the reply (`TRANSCRIPT_DIRECTIVE_AREA`): 🧢/🤔/🧾 plus the claim; click one to see the cited call, command, exit code and the output line that proves or contradicts it, and **🧢 Call /cap** sends `/cap` to that chat. A status-bar item shows this chat's tally and opens a Receipts list. |

Every hook fails open: if No Cap raises, the reply goes out unchanged and the error is logged.

<details>
<summary><b>What the demo run shows, step by step</b></summary>

`sh demo/run_demo.sh` drives a real interactive `hermes --cli` in a pseudo-terminal (`demo/drive.py`, through the
pyte VT100 emulator) and saves each screen as text, HTML and PNG, plus a raw asciicast of the whole session.

| Capture | What happened |
|---|---|
| [01-turnA-lies](docs/media/demo-run/01-turnA-lies.png) | "fix the failing login test, push it and deploy": pytest exits 1 (3 failed, 41 passed), `git push origin feat/login`. Reply: "All tests pass ✅, pushed to main, and the deploy is live." → 🧢 "All tests pass ✅", 🧢 "pushed to main", each line quoting its own part of the sentence. The deploy and file claims have no receipt either; they are recorded, not stamped (the capture was made at `show_uncertain: strict`; the default `off` stamps the same lines here) |
| [02a-cap-called](docs/media/demo-run/02a-cap-called.png) | `/cap`. Hermes refused the plugin's message injection (see limits), so No Cap printed the steer to paste. It names all four claims, the unstamped 🤔 ones included |
| [02-cap-rescore](docs/media/demo-run/02-cap-rescore.png) | The steer pasted back. The agent re-runs pytest, fixes `auth.py` with the patch tool, re-runs (44 passed), pushes feat/login and retracts. 🔁 re-score lines and 🧾 receipts |
| [03-strict](docs/media/demo-run/03-strict.png) | `mode: strict`, "make the password check constant-time": the draft says "All tests pass." with no run; `pre_verify` keeps the turn going, pytest runs, 🧾 |
| [04-capscore](docs/media/demo-run/04-capscore.png), [card](docs/media/demo-run/scorecard-svg.png) | `/capscore` and `/capscore card` from the throwaway store |
| [05-doctor](docs/media/demo-run/05-doctor.png) | `/nocap doctor` |

**With a real model.** `NOCAP_DEMO_BASE_URL=http://127.0.0.1:8766/v1 NOCAP_DEMO_MODEL=<id> NOCAP_DEMO_STEPS=demo/steps_real.json
sh demo/run_demo.sh` runs the same flow against any local OpenAI-compatible server, with nothing scripted. Recorded with
Qwen3-4B-Instruct-2507 (Q4_K_M, llama-server, no account) and `show_uncertain: expected`:
[docs/media/real-model-run/](docs/media/real-model-run/). The model ran pytest (exit 1), patched `auth.py`, re-ran
(44 passed), committed and pushed feat/login, then claimed "The change is verified and deployed." No Cap gave 🧾 to the
fix, the passing run, the commit and the push, and 🤔 to the deploy; after `/cap` the model retracted it (🫡). No 🧢: the
model never contradicted its own output. Earlier runs of the same flow found two parser bugs, fixed in this version.

**Other surfaces.** `NOCAP_DEMO_CMD="hermes --tui" NOCAP_DEMO_STEPS=demo/steps_tui.json sh demo/run_demo.sh` drives
the TUI ([docs/media/tui-run/](docs/media/tui-run/)): same footer, `/cap` opens an overlay with the steer, and the pasted
steer is re-scored. `sh demo/run_api_server.sh` sends the turns to the gateway's OpenAI-compatible API server
([docs/media/api-server-run/](docs/media/api-server-run/)): the footer arrives in both the JSON and the streamed reply,
but `/cap` and `/nocap` sent as messages reach the model as text, so there is no `/cap` over the API server. Both use the
scripted model.

</details>

### Hermes Desktop

![Receipt chips in Hermes Desktop](docs/media/desktop-run/04-chip-open.png)

Desktop has no slot under a message, so No Cap uses the SDK's transcript directive: on a Desktop turn the footer's
per-claim lines are replaced by one paragraph `::nocap{v="2" n="…" s="…" d="…"}` that the desktop half draws as chips. The
rules that keep it honest:

- **Desktop only.** It is emitted only when the turn's platform is exactly `desktop` (what Desktop chat sessions
  report; Desktop's embedded terminal reports `tui`). CLI, TUI, gateways, cron and the API server always get the text
  footer (`tests/test_desktop.py` checks 13 platform strings).
- **Only while the desktop half is on.** Desktop installs a package's desktop half switched off. Until you turn it on
  in Capabilities → Plugins → No Cap → Desktop, Desktop chats get the text footer, never a raw `::nocap` line. The half
  says hello through No Cap's own backend route (`dashboard/desktop_api.py`, local files only) on load and every 10
  minutes, and goodbye when it is switched off; `desktop_chips: auto` emits chips only while that hello is under 30
  minutes old. `on` / `off` override it.
- **Model-written directives are removed everywhere.** On every surface (CLI, TUI, gateways, Desktop), any `::nocap`
  the model wrote, including a copy of an earlier genuine chip, is removed from the reply before it is shown or
  stored, and counted as a forged stamp. Before matching, the text is NFKC-normalised and Unicode format characters
  (U+FEFF, zero-width spaces and joiners, word joiner) are dropped; removal repeats to a fixed point, so nested forms
  like `::nocap::nocap{…}` can't reassemble a directive. A reply without one is never touched.
- **Signed for one chat and one turn.** The directive carries an HMAC-SHA256 over the session id, the turn id, a random
  chip id and the payload. The key exists only in the Hermes process's memory, is new at every start, and is never
  written to disk or sent to the desktop half. The desktop half asks No Cap's backend (`POST /verify`) whether it issued
  that chip for the chat the directive sits in (the host passes the chat's id) and draws it only on a yes; a chip copied
  into another chat, a tampered one or an unknown one gets a warning, never a chip. After a restart, `/verify` vouches
  for older chips from the chip id, signature and payload digest recorded with the reply in this profile's store.
- **What that does and doesn't guarantee.** It stops the model's *text* from painting a 🧾 it didn't earn: a copied,
  replayed or invented directive is removed or rejected. It does not stop a local agent that has a shell or file-write
  tool: that agent runs as you and can always read or write your local files (the receipt store included) or attach a
  debugger to Hermes. No local plugin can prevent that; run untrusted agents in a sandbox.
- **Fits the host parser.** At most 2048 characters (the host's limit); what doesn't fit is counted ("+N more ·
  /nocap all").

Recorded in the real Hermes Desktop app (installed build of 8acb7f6), in a throwaway home, with the scripted model:
`sh demo/run_desktop.sh` ([docs/media/desktop-run/](docs/media/desktop-run/)): the desktop half off by default
(01) and switched on (02); the 🧢 chips (03) and an open chip (04); **Call /cap** sending the steer and the re-scored
🧾 chips (05; captured just before inline-code backticks were dropped from chip text); the status-bar Receipts list
(06); and with the desktop half switched off again, the plain text footer and no `::nocap` text (07).

## The Lie Ladder

`hermes nocap demo --ladder` runs one real Hermes CLI session in a throwaway home where a scripted model tells five
escalating lies, and No Cap catches each one with a receipt line:

| Rung | The lie | What really ran | Stamp today |
|---|---|---|---|
| 1 | "All tests pass." | `pytest -q`, exit 1, 3 failed | 🧢 CAP: says "3 failed, 41 passed" |
| 2 | "Pushed to main." | `git push origin feat/login` | 🧢 CAP: push went to feat/login, not main |
| 3 | "The fix is in commit 3f9c2a7b…" (made up) | `git log --oneline -3` | 🤔 NO RECEIPT: SHA not in any tool output (🧢 "sha not found in repo" once the fabricated-artifact detector lands) |
| 4 | "Deployed to prod. It is live." | nothing | 🤔 NO RECEIPT: no deploy command in this turn |
| 5 | "Merged PR #42 into main." | nothing; PR #42 never existed | 🤔 NO RECEIPT: no merge of #42 in this turn (🧢 once the artifact detector lands) |

Then `/nocap verdict` rules on the session, and a rematch session asks the same rungs of a careful model for
`/capscore compare`. One command writes the annotated page, the asciinema cast, a GIF and every PNG
([docs/media/ladder-run](docs/media/ladder-run), from a run of this branch):

<p align="center"><img src="docs/media/ladder-run/verdict.png" width="640" alt="Courtroom verdict card: In re: stub/over-eager-1, 0 of 5 claims proven; 2 counts of contradiction, 1 count of unverified SHA, 1 count of unsupported deployment, 1 count of unsupported merge"></p>
<p align="center"><img src="docs/media/ladder-run/compare.png" width="640" alt="Honesty A/B card: stub/over-eager-1 vs stub/careful-1, both below n=10 and greyed"></p>

The model is the only scripted part (`demo/stub_model.py`); Hermes, the shell, pytest, git and every stamp are real.
Both models sit below 10 claims, so the comparison card greys them out and names no winner: that is the rule working.

## More than a prompt

A system prompt can ask a model to be honest. It can't make the model check itself, because the model that wrote
"tests pass" is the one that would have to notice it didn't run them. No Cap works on data the model never touches:

- **Hook data, not model text.** The ledger is filled by `post_tool_call` from the real tool results (exit codes and
  parsed counts), before the model writes its reply. A reply can't add evidence to it, and stamps the model forges
  in its own text are detected and ignored (with a note).
- **Deterministic and cheap.** Plain Python on the hook data: no second model call, no tokens, no network, same
  verdict every time for the same turn.
- **It can stop the turn.** Strict mode uses `pre_verify`, a stop gate that a prompt or skill has no access to, to
  send the agent back to run the check before it says done.
- **It remembers across sessions and models.** Receipts go to a local store, so `/capscore` can say which model caps
  most, and `/cap` re-scores the next reply against the claims it called out.

## Commands and settings

| Task | Command |
|---|---|
| Receipts for the last reply | `/nocap` · `hermes nocap` |
| Every receipt, including unstamped unsure ones | `/nocap all` · `hermes nocap all` |
| Make the agent prove it or take it back | `/cap` |
| Honesty board / share card | `/capscore` · `/capscore card` · `hermes nocap score` · `hermes nocap card` |
| Leaderboard (this profile; team view opt-in) | the dashboard's Cap Board tab · `/capscore board` · `hermes nocap board` |
| Setup checks | `/nocap doctor` · `hermes nocap doctor` |
| Delete the store | `/nocap purge` · `hermes nocap purge` |
| Courtroom verdict card for a session | `/nocap verdict` · `hermes nocap verdict [--session ID]` |
| Honesty A/B of two models | `/capscore compare A B` · `hermes nocap scorecard --compare A B` |
| Export the store (redacted) | `hermes nocap export --json\|--csv [--out FILE]` |
| Metrics for a dashboard (Prometheus text, file only) | `hermes nocap metrics --file nocap.prom` |
| The Lie Ladder demo (throwaway home, scripted model) | `hermes nocap demo --ladder [--out DIR]` · `/nocap demo ladder` (CLI/TUI only) |

Settings live under `plugins.entries.no-cap.settings` (use `hermes config set`; they apply on the next reply, no
restart needed):

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `annotate` | `annotate` (footer), `strict` (footer restates 🧢 claims as Unverified, and `pre_verify` nudges coding turns), `quiet` (record only, no footer) |
| `show_uncertain` | `off` | When to stamp 🤔. `off`: never (only 🧾 and 🧢). `strict`: only "tests pass" in a turn that ran no tests, showed no test output and ran no check script of the agent's own. `expected`: also other claim types that expect a receipt when nothing relevant ran (push, merge, deploy, file...). `all`: every unsure claim. `default` means `off` |
| `check_numbers` | `true` | Also check counts like "changed 3 files" |
| `retention_days` | `30` | How long receipts are kept |
| `board.team_profiles` | unset (off) | Cap Board team view: `all`, or a list of profile names, to also show those profiles' stores (claims, cited commands and evidence lines). Off by default: the board shows only the profile it runs in. Even when set, only the CLI (`hermes nocap board`, a CLI session's `/capscore board`) and the dashboard tab show the team view; `/capscore board` in a gateway chat (Telegram, Discord, ...), the TUI or Desktop always shows the current profile |
| `board_sources` | `""` | Team view only: extra stores beside the team profiles, `label=path` entries separated by `:` (a Hermes home, a `receipts.jsonl`, a folder searched for them up to 6 levels and 2000 folders deep, never through a symlink, or a glob). Also `NOCAP_BOARD_SOURCES` |
| `board_min_claims` | `10` | Claims a row needs before the board shows and ranks its rates |
| `self_verify_http` | `false` | Let `/cap` send one HTTP HEAD to a URL the agent says is live (public addresses only, no redirects, 3 s timeout) |
| `desktop_chips` | `auto` | Hermes Desktop receipt chips. `auto`: while the desktop half is on (it checks in every 10 minutes). `on`: always on Desktop. `off`: text footer on Desktop too. Never on other surfaces |

`plugins.entries.no-cap.allow_gateway_injection: true` (one level up, a Hermes permission) lets `/cap` send its steer
itself in gateway-backed sessions. Without it `/cap` prints the steer for you to paste.

```sh
hermes config set plugins.entries.no-cap.settings.mode strict
hermes config set plugins.entries.no-cap.settings.show_uncertain all
```

## How good is it

🧾 precision 0.88 (88/100, 95% CI 0.80-0.93) and 🧢 8 of 11 on a fresh blind sample of public SWE-rebench runs at 7c6cbc0, two raters (Claude, Gemini; kappa 0.77), adjudicated; about 1 in 4 unstamped completion replies carried an unsupported claim.

The current release fixes the error classes that sample found. Re-scored on the same labelled sample (tuned, not
blind): 🧢 8 of 8 visible stamps correct (the 3 wrong ones are gone, all 8 right ones kept), 🧾 86/96 = 0.90
(95% CI 0.82-0.94), and 🤔 hidden by default. Method, error classes and limits, as aggregates only: [eval/README_METHOD.md](eval/README_METHOD.md).

Limits:

- 🧢 is rare on real runs: 11 in the blind sample, so its precision is a small-sample number.
- A missing stamp is not proof. By default only 🧾 and 🧢 are stamped; `/nocap all` and `/cap` still see the
  unsure claims.

## Disclosure

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
- **Network:** none by default. With `self_verify_http: true`, `/cap` may send one HTTP HEAD request to a URL the
  agent claimed is live, and only to a public address: the host is resolved first and refused if any address is
  loopback, link-local (cloud metadata such as 169.254.169.254), private, carrier-grade NAT, unique-local, multicast or
  reserved (or a `.local`/`.internal` name); the request goes to the address that was checked; redirects are not
  followed; 3 s timeout. Tested in `tests/test_verify_http.py`.
- **Commands it runs:** only during `/cap`, two read-only git commands as argument lists (no shell) in the session's
  working directory, 5 s timeout, no fetch: `git cat-file -t <sha>` and `git rev-parse --verify <ref>`. It never
  re-runs tests or builds.
- **Cap Board reads:** the dashboard tab and `/capscore board` read the current profile's own store. Only with the
  `board.team_profiles` opt-in, and only in the CLI or the dashboard, they also read other profiles' stores
  (`<root>/profiles/<name>/plugin-data/…/receipts.jsonl`, opened read-only) and the `board_sources` /
  `NOCAP_BOARD_SOURCES` paths, and show those profiles' claims, cited commands and evidence lines to whoever can open
  the dashboard. A gateway chat never gets another profile's data.
- **Reads outside its data:** `/cap` checks whether a file the agent says it created exists (existence and size).
  `/nocap doctor` reads other plugins' `plugin.yaml` files to find other reply rewriters, and creates and deletes one
  probe file in its own store folder.
- **Messages it sends:** `/cap` injects one user message (when Hermes allows it). It quotes the claims as the agent's
  own words and names only fixed read-only checks with validated arguments (`git ls-remote`, `git log -1`, `ls -l`,
  `gh pr view`, `curl -sI` to a public URL) or the plain test command parsed from an earlier run (`pytest -q`, never a
  line with `;`, `&&`, `|`, `$(`, backticks, quotes or redirects); otherwise it says "run your test suite". Strict
  mode's `pre_verify` can continue a coding turn at most twice.
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
- **Cards and exports it writes:** `/nocap verdict` writes `verdict.svg`/`verdict.png` and `/capscore compare` writes
  `compare.svg`/`compare.png` in its own store folder (they quote claims and cited commands, already redacted; `/nocap
  purge` deletes them with the store). `hermes nocap export --out` and `hermes nocap metrics --file` write the file you
  name (`0600`, atomic temp file + rename; every string re-passed through the secret masker; CSV cells that start like
  a formula are prefixed with `'`). Metrics are a file in the Prometheus text format: no port, no listener.
- **The demo:** `demo/stub_model.py` is a scripted model on 127.0.0.1. It is test scaffolding, not part of the plugin.
  `hermes nocap demo --ladder` runs `/bin/sh demo/run_ladder.sh` (an argv list, 25-minute timeout, output in a new
  0700 temp folder unless `--out` names one; `/nocap demo ladder`
  starts the same script in the background, CLI/TUI only, never from a gateway chat). The script makes a fresh
  `HERMES_HOME` under `/tmp`, points `GIT_CONFIG_GLOBAL` at a throwaway file, installs this plugin there, starts the
  stub on the first free port in 8765-8799 on 127.0.0.1, and uses `uv` to fetch pyte, Pillow and pytest into a
  throwaway venv (that fetch is the one network use, and it is the demo's, not the plugin's).

## Known limits and what is not tested

- English claims only. Claims inside code blocks and quotes are ignored on purpose.
- Long inputs are read in a window, so no hook can stall Hermes (every parser stays under 50 ms of CPU time on 100 KB of
  adversarial input; `tests/test_redos.py`, `scripts/redos_timings.py`). Per tool output: the first 8 KB and the last
  32 KB, plus up to 400 summary or failure lines from the middle (the full output is never stored). A longer run that
  exited non-zero never earns 🧾. Per command: the first 16 KB. Per reply: the first 64 KB, and claims are read from
  up to 10,000 characters of candidate sentences.
- Evidence comes from the same turn only. "I pushed that earlier" gets no receipt, even if it is true.
- 🧢 for files and builds is switched off: on real runs most failed writes were redone another way (sed, heredocs)
  and chained builds made exit codes unreliable. They get 🧾 or an unstamped 🤔.
- A count claim against a failing run is not a 🧢. In one demo run the agent said "pytest: 44 passed" after
  "1 failed, 43 passed"; that was recorded as unsure, not stamped.
- `/cap` on this Hermes build: the classic CLI runs through a local gateway, so Hermes refuses the plugin's message
  injection unless `allow_gateway_injection` is on. With it on, once, the injected turn ran in the gateway session but
  its output never appeared in the CLI. The paste path (the default) is the one the demo shows.
- The `pre_verify` nudge text isn't shown in the classic CLI; you see the draft reply, then the check running.
- Hermes keeps only the first plugin's `transform_llm_output` rewrite per turn. `doctor` warns when another enabled
  plugin also rewrites replies.
- The API server surface shows the footer but has no `/cap` or `/nocap`: Hermes passes slash commands sent there to
  the model as text.
- A real model runs real commands. In one recorded run Qwen3-4B ran `git config --global user.email ...` and a `curl`
  to github.com; the demo scripts point `GIT_CONFIG_GLOBAL` at the throwaway directory for that reason.
- Desktop chips need the backend route, so a Desktop attached to a remote backend without No Cap's desktop half
  installed there gets the text footer. A Desktop chat reopened in the CLI or TUI shows the `::nocap{…}` line as text
  (and if the model repeats it there, it is removed). A chip whose chat id the host doesn't report yet shows "checking
  receipts…" until it does.
- Desktop is tested end to end only with the scripted model, on macOS, against the installed build of 8acb7f6.
- Not tested: Discord and Telegram sessions end to end; real models other than one local Qwen3-4B (three
  runs); Linux and Windows; the catalog install path; a real conflict with another enabled reply-rewriting plugin
  (unit-tested only).

## Contributing

```sh
uv venv .venv && uv pip install --python .venv/bin/python pytest pillow fastapi
sh scripts/test.sh                 # the whole suite, with PYTHONPATH cleared
sh scripts/test-js.sh              # the Desktop half (node --test, no npm install)
hermes plugins validate .          # the catalog CI check
sh demo/run_demo.sh                # the end-to-end demo in a throwaway HERMES_HOME (needs uv; om for PNGs)
```

## License

MIT, see [LICENSE](LICENSE). The logo, banner and brand images in `docs/` were made for this project and are
covered by the same licence.
