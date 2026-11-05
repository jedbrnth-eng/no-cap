#!/bin/sh
# No Cap end-to-end demo: a REAL interactive Hermes CLI session in a THROWAWAY HERMES_HOME.
#
# What is real: Hermes (classic CLI), its terminal and patch tools, the shell, pytest, git (local bare
# origin), the plugin installed from this checkout with `hermes plugins install`, every stamp it prints.
# What is scripted: the model. demo/stub_model.py is a local OpenAI-compatible endpoint on 127.0.0.1 that
# plays an over-eager agent so the lie repeats on cue. Say so wherever the output is shown.
#
#   sh demo/run_demo.sh                  writes docs/media/demo-run/ (txt + html + png + session.cast)
#   NOCAP_DEMO_KEEP=1 sh demo/run_demo.sh   keep the throwaway home for poking around
#
# Needs: hermes on PATH, uv (for pyte, the VT100 emulator the driver uses, and pytest for the demo repo),
# om (optional, renders the PNGs). The real ~/.hermes is never read or written: HERMES_HOME points at a
# fresh mktemp dir under /tmp. (It has to be outside ~/.hermes: Hermes treats a home inside the real root
# as the default profile and hands it to the host gateway instead of starting its own.)
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${NOCAP_DEMO_OUT:-$ROOT/docs/media/demo-run}"
PORT="${NOCAP_DEMO_PORT:-8765}"
AGENT_DIR="${HERMES_AGENT_DIR:-$HOME/.hermes/hermes-agent}"
WORK="$(cd "$(mktemp -d /tmp/nocap-demo.XXXXXX)" && pwd -P)"
export HERMES_HOME="$WORK/home"
unset PYTHONPATH
mkdir -p "$HERMES_HOME"
# A real model may run `git config --global ...` (one did). Point git's global config at the throwaway dir so the
# session can never rewrite the user's ~/.gitconfig, and give it a demo identity so it has no reason to try.
export GIT_CONFIG_GLOBAL="$WORK/gitconfig"
printf '[user]\n\tname = demo\n\temail = demo@localhost\n' >"$GIT_CONFIG_GLOBAL"

# Real-model mode: NOCAP_DEMO_BASE_URL=<local OpenAI-compatible URL> NOCAP_DEMO_MODEL=<id> skips the stub, and
# NOCAP_DEMO_STEPS picks the step file (demo/steps_real.json fits a model that doesn't follow the script).
# NOCAP_DEMO_CMD="hermes --tui" NOCAP_DEMO_STEPS=demo/steps_tui.json drives the TUI instead of the classic CLI.
BASE_URL="${NOCAP_DEMO_BASE_URL:-}"
MODEL="${NOCAP_DEMO_MODEL:-stub/over-eager-1}"
STEPS="${NOCAP_DEMO_STEPS:-$ROOT/demo/steps.json}"
STUB_PID=""
cleanup() {
  [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null || true
  # the CLI starts a gateway (and language servers) for this home; stop exactly those, matched by HERMES_HOME,
  # and wait for them to exit (a gateway writes .clean_shutdown on the way out)
  pids=$(ps eww -Ao pid=,command= | awk -v h="HERMES_HOME=$HERMES_HOME " -v me="$$" 'index($0" ", h) && $1 != me {print $1}')
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  i=0; while [ $i -lt 50 ]; do
    alive=""; for p in $pids; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ -z "$alive" ] && break; i=$((i+1)); sleep 0.1
  done
  if [ -z "${NOCAP_DEMO_KEEP:-}" ]; then rm -rf "$WORK"; else echo "kept: $WORK"; fi
}
trap cleanup EXIT INT TERM

step() { printf '\n== %s\n' "$*"; }

if [ -n "$BASE_URL" ]; then
  step "1/6 real model $MODEL at $BASE_URL (nothing scripted)"
  curl -sf "$BASE_URL/models" >/dev/null || { echo "no model server at $BASE_URL" >&2; exit 3; }
else
  step "1/6 scripted model on 127.0.0.1:$PORT (disclosed: the only fake part)"
  if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    echo "port $PORT is busy; set NOCAP_DEMO_PORT" >&2; exit 2
  fi
  python3 "$ROOT/demo/stub_model.py" "$PORT" >"$WORK/stub.log" 2>&1 &
  STUB_PID=$!
  i=0; until curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null; do i=$((i+1)); [ $i -gt 50 ] && exit 3; sleep 0.1; done
  cat "$WORK/stub.log"
  BASE_URL="http://127.0.0.1:$PORT/v1"
fi

step "2/6 throwaway Hermes home: $HERMES_HOME"
hermes plugins install "file://$ROOT" --enable --yes-deps 2>&1 | grep -E "Installed|enabled|Error" || true
hermes config set model.provider custom >/dev/null
hermes config set model.base_url "$BASE_URL" >/dev/null
hermes config set model.default "$MODEL" >/dev/null
hermes config set model.api_key not-a-real-key >/dev/null
[ -n "${NOCAP_DEMO_CTX:-}" ] && hermes config set model.context_length "$NOCAP_DEMO_CTX" >/dev/null
hermes config set plugins.entries.no-cap.settings.mode annotate >/dev/null
# show_uncertain stays at the plugin default (off) unless NOCAP_DEMO_SHOW_UNCERTAIN says otherwise: the unsure
# deploy/file claims of turn A are recorded but not stamped, and /cap still names them
[ -n "${NOCAP_DEMO_SHOW_UNCERTAIN:-}" ] && hermes config set plugins.entries.no-cap.settings.show_uncertain \
  "$NOCAP_DEMO_SHOW_UNCERTAIN" >/dev/null
# allow_gateway_injection stays OFF (the default). On this Hermes build the classic CLI talks to a local
# gateway, so /cap can't inject its steer and prints it instead; the driver pastes it back, as a user would.
# (With the opt-in on, the injected turn ran in the gateway session but its output never reached the CLI.)
# answer the first-run metrics question up front ("No thanks") so it doesn't sit in the recording
(cd "$AGENT_DIR" && "$AGENT_DIR/venv/bin/python" -c \
  "from hermes_cli.observability.shared_metrics_consent import save_consent; save_consent(False, False)")
hermes plugins list --plain --no-bundled 2>&1 | grep -i no-cap || { echo "no-cap not installed" >&2; exit 4; }

step "3/6 demo repo (3 of 44 tests fail; local bare origin; on feat/login)"
sh "$ROOT/demo/setup_repo.sh" "$WORK/demo"
uv venv -q "$WORK/venv" && uv pip install -q --python "$WORK/venv/bin/python" pytest
mkdir -p "$WORK/bin" && ln -s "$WORK/venv/bin/pytest" "$WORK/bin/pytest"
(cd "$WORK/demo/login-app" && "$WORK/bin/pytest" -q -p no:cacheprovider | tail -1) || true

step "4/6 drive a real 'hermes --cli' session in a pty (turn A lie, /cap, strict turn, /capscore, doctor)"
rm -rf "$OUT"; mkdir -p "$OUT"
cd "$WORK/demo/login-app"
PATH="$WORK/bin:$PATH" uv run -q --with pyte python3 "$ROOT/demo/drive.py" \
  --cmd "${NOCAP_DEMO_CMD:-hermes --cli}" --out "$OUT" --steps "$STEPS"

step "5/6 artefacts from the throwaway store"
for f in "$HERMES_HOME"/plugin-data/*/scorecard.png "$HERMES_HOME"/plugin-data/*/scorecard.svg; do
  [ -f "$f" ] && cp "$f" "$OUT/"
done
python3 - "$HERMES_HOME" "$OUT" <<'PY'
import glob, json, sys
from collections import Counter
recs = [json.loads(l) for p in glob.glob(sys.argv[1] + "/plugin-data/*/receipts.jsonl") for l in open(p)]
replies = [r for r in recs if r.get("type", "reply") == "reply"]
lines = [f"store records: {len(recs)} ({len(replies)} checked replies)"]
for i, r in enumerate(replies, 1):
    c = Counter((x["verdict"] + (" (unstamped)" if x.get("hidden") else "")) for x in r.get("receipts", []))
    lines.append(f"reply {i} · mode {r.get('mode')} · calls: " + ", ".join(
        f"{k['i']}:{k['tool']}" + (f"(exit {k['exit']})" if k.get("exit") is not None else "") for k in r.get("calls", []))
        + " · " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
open(sys.argv[2] + "/ledger-summary.txt", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
PY
git --git-dir="$WORK/demo/origin.git" branch --format='%(refname:short)' | sed 's/^/origin.git has branch: /' | tee "$OUT/origin-branches.txt"

step "6/6 PNG renders of the captured screens"
python3 "$ROOT/demo/render_media.py" "$OUT"
echo "done: $OUT"
