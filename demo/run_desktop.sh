#!/bin/sh
# No Cap in the real Hermes Desktop app, in a THROWAWAY home: proves the receipt chips render.
#
# Isolation (same knobs as apps/desktop/e2e/fixtures.ts): HOME, HERMES_HOME and Electron userData all live under a
# fresh /tmp dir, HERMES_DESKTOP_ISOLATED_BACKEND=1 gives the app its own backend, a unique HERMES_DESKTOP_APP_NAME
# avoids the single-instance lock of a Desktop you already run, and the hermes:// handler is not re-registered.
# Your real ~/.hermes and ~/Library/Application Support/Hermes are never read or written.
#
# The model is demo/stub_model.py (scripted, disclosed: the only fake part). Hermes, Desktop, the terminal tool,
# pytest, git (local bare origin) and No Cap are real.
#
#   sh demo/run_desktop.sh            starts everything and prints WORK + the CDP port; Ctrl-C stops and wipes it
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${NOCAP_DESKTOP_APP:-/Applications/Hermes.app/Contents/MacOS/Hermes}"
AGENT_DIR="${HERMES_AGENT_DIR:-$HOME/.hermes/hermes-agent}"
STUB_PORT="${NOCAP_DESKTOP_STUB_PORT:-8771}"
CDP_PORT="${NOCAP_DESKTOP_CDP_PORT:-9339}"
WORK="$(cd "$(mktemp -d /tmp/nocap-desktop.XXXXXX)" && pwd -P)"
HH="$WORK/hermes-home"
UD="$WORK/electron-user-data"
mkdir -p "$HH/plugins" "$UD"
[ -x "$APP" ] || { echo "Hermes Desktop not found at $APP" >&2; exit 2; }

STUB_PID="" APP_PID=""
cleanup() {
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null || true
  sleep 1
  pids=$(ps eww -Ao pid=,command= | awk -v h="HERMES_HOME=$HH" -v me="$$" 'index($0, h) && $1 != me {print $1}')
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  if [ -z "${NOCAP_DEMO_KEEP:-}" ]; then rm -rf "$WORK"; else echo "kept: $WORK"; fi
}
trap cleanup EXIT INT TERM

printf '[user]\n\tname = demo\n\temail = demo@localhost\n' >"$WORK/gitconfig"
GIT_CONFIG_GLOBAL="$WORK/gitconfig" sh "$ROOT/demo/setup_repo.sh" "$WORK/demo" >/dev/null
uv venv -q "$WORK/venv" && uv pip install -q --python "$WORK/venv/bin/python" pytest

# The plugin: this checkout, linked (Desktop syncs desktop/plugin.js from a linked package by content).
ln -s "$ROOT" "$HH/plugins/no-cap"
cat >"$HH/config.yaml" <<EOF
model:
  provider: custom
  default: stub/over-eager-1
  base_url: http://127.0.0.1:$STUB_PORT/v1
  context_length: 128000
custom_providers:
  - name: Stub
    base_url: http://127.0.0.1:$STUB_PORT/v1
    key_env: OPENAI_API_KEY
auxiliary:
  title_generation:
    enabled: false
approvals:
  mode: "off"
onboarding:
  run: false
terminal:
  cwd: $WORK/demo/login-app
plugins:
  enabled: [no-cap]
  entries:
    no-cap:
      allow_gateway_injection: true
EOF
printf 'OPENAI_API_KEY=not-a-real-key\nOPENAI_BASE_URL=http://127.0.0.1:%s/v1\n' "$STUB_PORT" >"$HH/.env"
printf '{"x":40,"y":40,"width":1280,"height":820,"isMaximized":false}\n' >"$UD/window-state.json"

python3 "$ROOT/demo/stub_model.py" "$STUB_PORT" >"$WORK/stub.log" 2>&1 &
STUB_PID=$!

env -i PATH="$WORK/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$HOME/.local/bin" \
  HOME="$WORK" TMPDIR="$WORK" LANG=en_US.UTF-8 USER="${USER:-demo}" \
  GIT_CONFIG_GLOBAL="$WORK/gitconfig" \
  HERMES_HOME="$HH" HERMES_DESKTOP_USER_DATA_DIR="$UD" HERMES_DESKTOP_ISOLATED_BACKEND=1 \
  HERMES_DESKTOP_HERMES_ROOT="$AGENT_DIR" HERMES_DESKTOP_APP_NAME="NoCapDemo-$$" \
  HERMES_DESKTOP_SKIP_QUIT_CONFIRM=1 HERMES_DESKTOP_SKIP_PROTOCOL_REGISTRATION=1 \
  "$APP" --remote-debugging-port="$CDP_PORT" >"$WORK/app.log" 2>&1 &
APP_PID=$!
echo "WORK=$WORK"
echo "CDP=http://127.0.0.1:$CDP_PORT"
wait "$APP_PID"
