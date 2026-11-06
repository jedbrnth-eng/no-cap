# Install run: a new user's No Cap install, from GitHub

What was run (v0.2.0, `main` at 6e6df8e; Hermes Agent and Hermes Desktop v0.23.0, macOS):

1. An empty `HERMES_HOME` under `/tmp`, git's global config pointed at a throwaway file, then the README's install
   lines word for word:
   `hermes plugins install jedbrnth-eng/no-cap --enable` (clones from GitHub, exit 0) and `hermes nocap doctor`
   ("0 problems found.", exit 0).
2. A model: `hermes config set model.*` pointing at the scripted [`demo/stub_model.py`](../../../demo/stub_model.py) on
   127.0.0.1 (the only fake part; Hermes, its tools, pytest, git with a local bare origin and No Cap are real), plus
   the demo repo from `demo/setup_repo.sh` (3 of 44 tests fail).
3. **Desktop:** the installed Hermes.app launched against that home in isolation (own backend, own user-data dir,
   same knobs as `demo/run_desktop.sh`), driven over CDP. Captures 01-06.
4. **Dashboard:** a second fresh home, same install, `hermes dashboard --port <free port> --no-open --skip-build`
   (`--skip-build` only skips rebuilding Hermes's own web UI), the **Cap Board** tab open in a browser while
   `hermes chat -Q --oneshot -q ...` turns ran in a terminal. Captures 10-14. The board updated by itself (4 s poll),
   no reload.

| File | What it shows |
|---|---|
| 01-installed-desktop-half-off.png | Capabilities → Plugins → "no cap" → the card, straight after install: agent half on, **Desktop** switch off, so the card header says Off |
| 02-desktop-half-on.png | the Desktop switch turned on (the half's hello reached No Cap's backend route) |
| 03-chips.png | "fix the failing login test, push it and deploy": pytest exits 1, the push goes to feat/login, the model says "All tests pass ✅, pushed to main". Two 🧢 chips and **Call /cap**; status bar 🧾 0 · 🧢 2 |
| 04-chip-open.png | the 🧢 "All tests pass ✅" chip opened: call 1 · terminal · `pytest -q` · exit 1 · "3 failed, 41 passed" |
| 05a-call-cap-default-config.png | **Call /cap** with the config the install leaves: Hermes refuses the injection, so No Cap prints the steer to paste |
| 05-call-cap-rescored.png | after `hermes config set plugins.entries.no-cap.allow_gateway_injection true` (no restart), **Call /cap** again: the agent re-runs pytest, fixes auth.py, 44 passed, retracts "pushed to main" and the deploy; 🔁 re-score lines and four 🧾 chips |
| 06-receipts-popover.png | the status-bar Receipts list for this chat: 🧾 4 · 🧢 2, both turns |
| 10-board-empty.png | the Cap Board on the fresh install, before any reply (captured before the "none yet" store line was added) |
| 11-board-after-1-turn.png | one `hermes chat` turn later: 4 claims, 2 🧢 in the Hall of Cap |
| 12-board-after-5-turns.png | after the Lie Ladder's rungs 1-4: 5 replies, 5 🧢, including the made-up SHA |
| 14-board-models.png | Models view after one `stub/careful-1` turn: its first 🧾, ranked separately; both rows greyed (n < 10) |

## Friction found, and what changed

| # | Where | Friction | Fix in this PR |
|---|---|---|---|
| 1 | README Install | Nothing told a Desktop user to turn on the desktop half; it was only in the Desktop section further down (and in the doctor) | Install section: the exact clicks |
| 2 | Desktop card | Right after `--enable` the card says **Off** (its header follows the desktop half), which reads as "the install didn't work" | Install section explains it |
| 3 | README Install | **Call /cap** on Desktop doesn't send anything with the installed config; the setting it needs was only in the Configuration section | Install section: the one `hermes config set` line |
| 4 | `/cap` fallback message and the doctor | Named the config key but not how to set it | Both now give `hermes config set plugins.entries.no-cap.allow_gateway_injection true` (tests in test_plugin.py, test_doctor.py) |
| 5 | Doctor's Desktop line | Said "Capabilities → Plugins" but the switch is inside the No Cap card | Now "Capabilities → Plugins → No Cap → Desktop (a switch)" (test in test_desktop.py) |
| 6 | README Install | No word on how to reach the Cap Board | Install section: `hermes dashboard` → Cap Board tab |
| 7 | Cap Board footer | On a fresh install it read "Stores (read-only):" with nothing after it | Now "none yet · the first checked reply creates this profile's store" (tests/js/board.test.mjs) |

Not friction for No Cap, noted: `hermes plugins install` into a brand-new home first prints "preparing dependencies for
this data root" and takes a little longer; that is Hermes setting up the new home.
