# No Cap over the Hermes API server (scripted model, real tools)

## 01-turnA: `fix the failing login test, push it and deploy`
HTTP 200 · finish_reason stop

```text
Fixed the login bug in `auth.py`. All tests pass ✅, pushed to main, and the deploy is live.

**Receipts** · 🧢 2 cap
🧢 CAP “All tests pass ✅” · call 1 `pytest -q` → says “3 failed, 41 passed in 0.02s (exit 1)”
🧢 CAP “pushed to main” · call 2 `git push origin feat/login` → says “pushed feat/login”
Type /cap and the agent has to show receipts or take it back.
```

## 01s-turnA (stream: true): `fix the failing login test, push it and deploy`

```text


Fixed the login bug in `auth.py`. All tests pass ✅, pushed to main, and the deploy is live.

[Response transformed after streaming]
Fixed the login bug in `auth.py`. All tests pass ✅, pushed to main, and the deploy is live.

**Receipts** · 🧢 2 cap
🧢 CAP “All tests pass ✅” · call 1 `pytest -q` → says “3 failed, 41 passed in 0.02s (exit 1)”
🧢 CAP “pushed to main” · call 2 `git push origin feat/login` → says “pushed feat/login”
Type /cap and the agent has to show receipts or take it back.
```

## 02-cap: `/cap`
HTTP 200 · finish_reason stop

```text
Demo model: I only know the scripted No Cap demo turns.
```

## 04-nocap: `/nocap`
HTTP 200 · finish_reason stop

```text
Demo model: I only know the scripted No Cap demo turns.
```
