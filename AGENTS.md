# AGENTS.md

No Cap is a Hermes Agent plugin (Python, stdlib only at runtime). It records what each tool call returned and
stamps the claims in the agent's final reply as proven (NO CAP) or contradicted (CAP). No network, no extra model.

## Commands
Run from the repo root. Python 3.11 or 3.12 (CI matrix).

- Setup: `python3.11 -m venv .venv && .venv/bin/python -m pip install --require-hashes --no-deps -r .github/requirements-ci.txt`
- Tests (Python): `sh scripts/test.sh -q` (unsets PYTHONPATH, uses `.venv`; ~4-5 min, 6000+ tests)
- Tests (Desktop JS): `sh scripts/test-js.sh` (node's built-in runner, no npm install)
- ReDoS gate: `.venv/bin/python -m pytest -c tests/pytest.ini tests/test_redos.py -q`
- Security lint: `.venv/bin/bandit -r nocap __init__.py -ll -q`
- Personal-data grep: `.venv/bin/python scripts/check_personal_data.py`
- gitleaks over history and tree (from CI, not run locally): `gitleaks git --config .gitleaks.toml --redact -v .`
- Install into Hermes (from README, not run locally): `hermes plugins install jedbrnth-eng/no-cap --enable && hermes nocap doctor`

## Verification path
- Add or extend a test in `tests/` for every claim pattern, parser or surface change, then run `scripts/test.sh`.
- Docs edits: `tests/test_docs_links.py` checks every local link and anchor (`scripts/check_links.py`).
- Desktop chip changes: `scripts/test-js.sh` plus `tests/test_desktop_js_contract.py`.
- Discord surface changes: also run `tests/test_redteam_round2.py`.
- Live check in Hermes: `/nocap doctor` should end with "0 problems found."

## Layout
- `__init__.py`: plugin entry; registers the hooks and slash commands through fail-open wrappers.
- `plugin.yaml`: plugin manifest.
- `nocap/evidence.py`: one tool call -> evidence record (facts only).
- `nocap/claims.py`: finds checkable claims in a reply; `nocap/lang.py` for non-English.
- `nocap/verdict.py`: matches claims to the ledger. `nocap/engine.py`: per-turn kernel.
- `nocap/tamper.py`: suite-tampering detection (skips, deleted tests, runner filters).
- `nocap/store.py`: local receipt store (one JSON line per checked reply).
- `dashboard/plugin_api.py`: Cap Board backend. `desktop/plugin.js`: Desktop receipt chips.
- `eval/`: evaluation method and data. `docs/`: user guide and feature docs.

## Rules
- CAP only when a tool output in the same turn says the opposite; missing or ambiguous evidence is NO_RECEIPT.
  Why: precision first, a false CAP is worse than a missed one (`nocap/verdict.py`).
- Never store raw tool output; only extracted facts and the matched summary line (<=160 chars, masked).
  Why: the store must not leak user data (`nocap/evidence.py`, README).
- Every hook entry point stays behind the fail-open wrappers in `__init__.py`.
  Why: an exception must leave the user's reply untouched.
- The reply text is never edited except to strip a forged `::nocap` directive and append the footer.
  Why: users must be able to trust the body is the model's own words.
- Runtime code stays stdlib only, with no network calls. Why: it is a core promise in the README.
- Tests use synthetic text, never real transcripts; no home paths or real emails in tracked files.
  Why: public repo; CI runs `scripts/check_personal_data.py` and gitleaks.

Learned something durable about this repo? Add one line here in your PR.
