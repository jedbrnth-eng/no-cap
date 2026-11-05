# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on this repository
(<https://github.com/jedbrnth-eng/no-cap/security/advisories/new>).

Please don't open a public issue, pull request or discussion for a vulnerability. Include:

- the No Cap version or commit SHA and your Hermes version;
- what an attacker controls (tool output, the model's reply, a URL, a file in the session's working directory...);
- a minimal reproduction (a tool output or reply that triggers it is ideal) and what happens.

You should get an acknowledgement within 3 days and a fix or a decision within 30 days. Credit goes in the
advisory unless you ask otherwise.

## Supported versions

| Version            | Supported |
| ------------------ | --------- |
| `main` (latest)    | yes       |
| 0.1.x              | yes       |
| anything older     | no        |

Fixes land on `main` and in the next tagged release; there are no backports.

## Scope

No Cap reads every tool call and every final reply of a Hermes session, so these are in scope:

- **Redaction.** Everything No Cap stores goes through `redact()` (`nocap/evidence.py`) first. A secret shape
  (API key, token, password assignment, URL credentials, private key...) that reaches `receipts.jsonl`, a
  scorecard or a footer unmasked is a vulnerability, and so is a regex that a crafted tool output can make run
  for seconds (ReDoS: Hermes stalls while it runs).
- **The /cap re-check allowlist.** `/cap` may only run the read-only checks listed in `nocap/verify.py`:
  `os.stat` of a claimed file, `git -C <cwd> cat-file -t <sha>` and `git -C <cwd> rev-parse --verify <ref>`,
  as argv lists with a timeout and no shell. Getting `/cap` (or anything else in No Cap) to run another
  command, pass shell syntax or options through, or write files is in scope.
- **The HTTP check.** With `self_verify_http` on (off by default), `/cap` sends one HTTP `HEAD` request to
  re-check a "URL is live" claim: public addresses only (checked after DNS resolution and pinned), no
  redirects, 3 s timeout. Reaching a private, loopback, link-local or metadata address (SSRF), following a
  redirect, or sending any request with the setting off is in scope.
- **Store permissions.** The store lives in the profile's `plugin-data/no-cap/` with the directory `0700` and
  files `0600`. A way to make No Cap create them readable by other users, follow a symlink to write elsewhere,
  or read another profile's store is in scope.
- **Rendering.** Receipt text comes from tool output and the model. Any UI that shows it (CLI footer, Desktop,
  dashboard) must treat it as untrusted text: script or HTML injection through receipt text, or forged
  🧾/🧢 stamps that No Cap shows as its own, are in scope.

Out of scope: claims No Cap gets wrong (a missed 🧢 or a wrong 🤔 is an accuracy bug: open a normal issue),
problems in Hermes itself (report those to NousResearch/hermes-agent), and attacks that need write access to
the user's `HERMES_HOME` already.

## What CI checks on every pull request

`.github/workflows/ci.yml`: the test suite on Python 3.11 and 3.12, the ReDoS time budget
(`tests/test_redos.py`), gitleaks over the full history (the only allowed hits are the fake secrets in
`tests/test_redaction.py`, see `.gitleaks.toml`), bandit on the plugin code (medium or higher fails), and a
personal-data grep. Actions are pinned to commit SHAs and the workflow token is read-only.
