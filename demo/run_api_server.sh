#!/bin/sh
# No Cap through a second Hermes surface: the gateway's OpenAI-compatible API server, in a THROWAWAY HERMES_HOME.
#
# Same demo repo and the same scripted model as run_demo.sh (demo/stub_model.py, disclosed), but the turns go in as
# HTTP requests to /v1/chat/completions on 127.0.0.1 instead of a terminal. Hermes, the gateway, its tools, pytest,
# git (local bare origin) and No Cap are real. No credentials: the API key is a made-up local one, written only to
# the throwaway home's .env, and the server listens on 127.0.0.1 only.
#
#   sh demo/run_api_server.sh        writes docs/media/api-server-run/ (requests, responses, transcript.md)
#
# Checks: the footer is in the HTTP reply (FAIL stops the script); whether /cap and /nocap sent as messages reach the
# plugin (NOTE when Hermes passes them to the model instead); the re-score when a steer comes back.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${NOCAP_API_OUT:-$ROOT/docs/media/api-server-run}"
STUB_PORT="${NOCAP_API_STUB_PORT:-8767}"
API_PORT="${NOCAP_API_PORT:-8650}"
KEY="nocap-local-test-key"
WORK="$(cd "$(mktemp -d /tmp/nocap-api.XXXXXX)" && pwd -P)"
export HERMES_HOME="$WORK/home"
export GIT_CONFIG_GLOBAL="$WORK/gitconfig"
printf '[user]\n\tname = demo\n\temail = demo@localhost\n' >"$GIT_CONFIG_GLOBAL"
unset PYTHONPATH
mkdir -p "$HERMES_HOME"
AGENT_DIR="${HERMES_AGENT_DIR:-$HOME/.hermes/hermes-agent}"

STUB_PID="" GW_PID=""
cleanup() {
  [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null || true
  [ -n "$GW_PID" ] && kill "$GW_PID" 2>/dev/null || true
  pids=$(ps eww -Ao pid=,command= | awk -v h="HERMES_HOME=$HERMES_HOME " -v me="$$" 'index($0" ", h) && $1 != me {print $1}')
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  sleep 1
  if [ -z "${NOCAP_DEMO_KEEP:-}" ]; then rm -rf "$WORK"; else echo "kept: $WORK"; fi
}
trap cleanup EXIT INT TERM
step() { printf '\n== %s\n' "$*"; }

for p in "$STUB_PORT" "$API_PORT"; do
  if curl -s -m 1 "http://127.0.0.1:$p/" >/dev/null 2>&1; then echo "port $p is busy" >&2; exit 2; fi
done

step "1/5 scripted model on 127.0.0.1:$STUB_PORT (disclosed: the only fake part)"
python3 "$ROOT/demo/stub_model.py" "$STUB_PORT" >"$WORK/stub.log" 2>&1 &
STUB_PID=$!
i=0; until curl -sf "http://127.0.0.1:$STUB_PORT/v1/models" >/dev/null; do i=$((i+1)); [ $i -gt 50 ] && exit 3; sleep 0.1; done

step "2/5 throwaway home $HERMES_HOME, plugin installed, API server on 127.0.0.1:$API_PORT"
hermes plugins install "file://$ROOT" --enable --yes-deps 2>&1 | grep -E "Installed|enabled|Error" || true
hermes config set model.provider custom >/dev/null
hermes config set model.base_url "http://127.0.0.1:$STUB_PORT/v1" >/dev/null
hermes config set model.default stub/over-eager-1 >/dev/null
hermes config set model.api_key not-a-real-key >/dev/null
(cd "$AGENT_DIR" && "$AGENT_DIR/venv/bin/python" -c \
  "from hermes_cli.observability.shared_metrics_consent import save_consent; save_consent(False, False)")
sh "$ROOT/demo/setup_repo.sh" "$WORK/demo" >/dev/null
hermes config set terminal.cwd "$WORK/demo/login-app" >/dev/null
printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\nAPI_SERVER_HOST=127.0.0.1\nAPI_SERVER_PORT=%s\n' "$KEY" "$API_PORT" \
  >>"$HERMES_HOME/.env"
uv venv -q "$WORK/venv" && uv pip install -q --python "$WORK/venv/bin/python" pytest
mkdir -p "$WORK/bin" && ln -s "$WORK/venv/bin/pytest" "$WORK/bin/pytest"
PATH="$WORK/bin:$PATH" hermes gateway run >"$WORK/gateway.log" 2>&1 &
GW_PID=$!
i=0; until curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; do
  i=$((i+1)); [ $i -gt 300 ] && { tail -30 "$WORK/gateway.log" >&2; exit 4; }; sleep 0.2
done
echo "gateway up: $(curl -s "http://127.0.0.1:$API_PORT/health")"

step "3/5 turns over HTTP (one session id for all of them)"
rm -rf "$OUT"; mkdir -p "$OUT"
rc=0
python3 - "$API_PORT" "$KEY" "$OUT" <<'PY' || rc=$?
import json, sys, urllib.request
port, key, out = sys.argv[1], sys.argv[2], sys.argv[3]
SID = "nocap-api-demo"
md = ["# No Cap over the Hermes API server (scripted model, real tools)\n"]


def ask(n, text, timeout=300):
    body = {"model": "hermes-agent", "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "X-Hermes-Session-Id": SID})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        status, raw = r.status, r.read().decode()
    open(f"{out}/{n}-response.json", "w").write(raw)
    data = json.loads(raw)
    reply = data["choices"][0]["message"]["content"] or ""
    md.extend([f"## {n}: `{text.splitlines()[0][:80]}`", f"HTTP {status} · finish_reason "
               f"{data['choices'][0].get('finish_reason')}", "", "```text", reply, "```", ""])
    print(f"--- {n} (HTTP {status})\n{reply}\n")
    return reply


def ask_stream(n, text, timeout=300):
    """Same turn with stream: true, in its own session: is the footer in the streamed deltas too?"""
    body = {"model": "hermes-agent", "stream": True, "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "X-Hermes-Session-Id": SID + "-stream"})
    parts = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    open(f"{out}/{n}-stream.sse", "w").write(raw)
    for line in raw.splitlines():
        if line.startswith("data: ") and line[6:].strip() != "[DONE]":
            try:
                ch = json.loads(line[6:])["choices"][0]
            except Exception:
                continue
            parts.append((ch.get("delta") or {}).get("content") or "")
    reply = "".join(parts)
    md.extend([f"## {n} (stream: true): `{text[:80]}`", "", "```text", reply, "```", ""])
    print(f"--- {n} streamed\n{reply}\n")
    return reply


a = ask("01-turnA", "fix the failing login test, push it and deploy")
s_ = ask_stream("01s-turnA", "fix the failing login test, push it and deploy")
c = ask("02-cap", "/cap")
steer = "\n".join(l for l in c[c.find("[No Cap] I'm calling cap"):].split("\n\n")[0].splitlines()) if "[No Cap]" in c else ""
b = ask("03-steer", steer) if steer else ""
n = ask("04-nocap", "/nocap")
open(f"{out}/transcript.md", "w").write("\n".join(md))
dispatched = "Cap called" in c or "Nothing to cap" in c
lines = [f"{'PASS' if 'Receipts' in a and '🧢 CAP' in a else 'FAIL'} footer on the HTTP reply (🧢 receipts in the content)",
         f"{'PASS' if 'Receipts' in s_ and '🧢 CAP' in s_ else 'NOTE'} footer in the streamed deltas (stream: true)",
         f"{'PASS' if dispatched else 'NOTE'} /cap as a message: " + (
             "handled by No Cap" if dispatched else "not dispatched as a plugin command; it reached the model as text"),
         f"{'PASS' if '🔁 /cap re-score' in b else ('SKIP' if not steer else 'FAIL')} steer re-scored",
         f"{'PASS' if 'Ledger:' in n else 'NOTE'} /nocap as a message: " + (
             "handled by No Cap" if "Ledger:" in n else "not dispatched; it reached the model as text")]
open(f"{out}/checks.txt", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(1 if any(l.startswith("FAIL") for l in lines) else 0)
PY

step "4/5 origin branches"
git --git-dir="$WORK/demo/origin.git" branch --format='%(refname:short)' | sed 's/^/origin.git has branch: /' | tee "$OUT/origin-branches.txt"
step "5/5 store"
for f in "$HERMES_HOME"/plugin-data/*/receipts.jsonl; do [ -f "$f" ] && wc -l <"$f" | sed 's/^/store records: /'; done
exit $rc
