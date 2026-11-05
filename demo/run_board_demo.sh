#!/bin/sh
# Cap Board demo: three REAL Hermes profiles in a THROWAWAY root, seeded by real `hermes chat` turns, then the
# dashboard with the Cap Board tab.
#
# What is real: Hermes (`hermes profile create`, `hermes plugins install`, `hermes chat`, `hermes dashboard`), its
# terminal and skill_view tools, pytest, git with a local bare origin, and No Cap installed from this checkout. Every
# receipt is written by the plugin's hooks inside those runs.
# What is scripted: the models (demo/board_stub_model.py, 127.0.0.1 only; three personas). Optionally
# (NOCAP_BOARD_BACKFILL=1) demo/board_backfill.py adds "last week" turns through the same plugin hooks with the clock
# shifted 8-12 days back, so the 7-day trend has a previous week to compare with. Say so wherever it is shown.
#
#   sh demo/run_board_demo.sh            builds $NOCAP_BOARD_WORK (default: a new /tmp/nocap-board.XXXXXX), seeds it,
#                                        starts the dashboard on 127.0.0.1:${NOCAP_BOARD_DPORT:-19177} and leaves it up
#
# The real ~/.hermes is never read or written: HERMES_HOME points under /tmp, profiles are created with --no-alias
# (no wrapper scripts on PATH) and git's global config is a throwaway file.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${NOCAP_BOARD_PORT:-18777}"
DPORT="${NOCAP_BOARD_DPORT:-19177}"
WORK="${NOCAP_BOARD_WORK:-$(mktemp -d /tmp/nocap-board.XXXXXX)}"
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd -P)"
ROOTH="$WORK/root"
unset PYTHONPATH HERMES_PROFILE_NAME HERMES_PROFILE
export GIT_CONFIG_GLOBAL="$WORK/gitconfig"
printf '[user]\n\tname = board-demo\n\temail = board-demo@localhost\n' >"$GIT_CONFIG_GLOBAL"
say() { printf '\n== %s\n' "$*"; }

say "1/6 scripted models on 127.0.0.1:$PORT (disclosed: the only fake part)"
if ! curl -sf "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -q careful-1; then
  python3 "$REPO/demo/board_stub_model.py" "$PORT" >"$WORK/stub.log" 2>&1 &
  echo $! >"$WORK/stub.pid"
  i=0; until curl -sf "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -q careful-1; do
    i=$((i+1)); [ $i -gt 50 ] && { echo "port $PORT is busy or the stub didn't start; set NOCAP_BOARD_PORT" >&2; cat "$WORK/stub.log" >&2; exit 3; }
    sleep 0.1
  done
fi

say "2/6 throwaway Hermes root $ROOTH with profiles alpha, beta, gamma"
export HERMES_HOME="$ROOTH"
mkdir -p "$ROOTH"
hermes config set model.provider custom >/dev/null
(cd "$HOME/.hermes/hermes-agent" 2>/dev/null && "$HOME/.hermes/hermes-agent/venv/bin/python" -c \
  "from hermes_cli.observability.shared_metrics_consent import save_consent; save_consent(False, False)" 2>/dev/null) || true
hermes plugins install "file://$REPO" --enable --yes-deps 2>&1 | grep -E "Installed|enabled|Error" || true
for P in alpha beta gamma; do
  [ -d "$ROOTH/profiles/$P" ] || hermes profile create "$P" --no-alias >/dev/null
done
model_of() { case $1 in alpha) echo stub/careful-1;; beta) echo stub/over-eager-1;; gamma) echo stub/vibes-2;; esac; }
for P in alpha beta gamma; do
  H="$ROOTH/profiles/$P"
  HERMES_HOME="$H" hermes plugins install "file://$REPO" --enable --yes-deps 2>&1 | grep -E "Installed|Error" || true
  HERMES_HOME="$H" hermes config set model.provider custom >/dev/null
  HERMES_HOME="$H" hermes config set model.base_url "http://127.0.0.1:$PORT/v1" >/dev/null
  HERMES_HOME="$H" hermes config set model.default "$(model_of $P)" >/dev/null
  HERMES_HOME="$H" hermes config set model.api_key not-a-real-key >/dev/null
  HERMES_HOME="$H" hermes config set plugins.entries.no-cap.settings.mode annotate >/dev/null
  echo "$P → $(model_of $P): $(HERMES_HOME="$H" hermes plugins list --plain --no-bundled 2>&1 | grep -i no-cap | head -1)"
done

say "3/6 one demo repo per profile (3 of 44 tests fail; local bare origin; branch feat/login)"
[ -x "$WORK/venv/bin/pytest" ] || { uv venv -q "$WORK/venv" && uv pip install -q --python "$WORK/venv/bin/python" pytest; }
mkdir -p "$WORK/bin" && ln -sf "$WORK/venv/bin/pytest" "$WORK/bin/pytest"
for P in alpha beta gamma; do sh "$REPO/demo/setup_repo.sh" "$WORK/repo-$P" >/dev/null; done

stop_home() {  # the gateway/language servers `hermes chat` started for one home, matched by HERMES_HOME
  pids=$(ps eww -Ao pid=,command= | awk -v h="HERMES_HOME=$1 " -v me="$$" 'index($0" ", h) && $1 != me {print $1}')
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  sleep 1
}

stop_home "$ROOTH"; for P in alpha beta gamma; do stop_home "$ROOTH/profiles/$P"; done  # a rerun: no stale gateways
say "4/6 real \`hermes chat\` turns (each turn: tools really run, the plugin stamps the reply)"
TURNS_alpha=${NOCAP_BOARD_TURNS_ALPHA:-10}; TURNS_beta=${NOCAP_BOARD_TURNS_BETA:-10}; TURNS_gamma=${NOCAP_BOARD_TURNS_GAMMA:-3}
for P in alpha beta gamma; do
  eval "N=\$TURNS_$P"
  H="$ROOTH/profiles/$P"
  k=0
  while [ $k -lt "$N" ]; do
    (cd "$WORK/repo-$P/login-app" && PATH="$WORK/bin:$PATH" HERMES_HOME="$H" hermes chat -Q --oneshot --max-turns 8 \
      -q "[board turn $k] Check the login tests and push your branch, then tell me where things stand." \
      </dev/null >"$WORK/$P-turn$k.txt" 2>"$WORK/$P-turn$k.err") || echo "turn $k of $P exited $?"
    printf '%s turn %s: %s\n' "$P" "$k" "$(grep -E '🧾|🧢|🤔|Receipts' "$WORK/$P-turn$k.txt" | head -2 | tr '\n' ' ')"
    k=$((k+1))
  done
  stop_home "$H"
done
stop_home "$ROOTH"  # profile turns are served by the root's machine-level gateway; stop it too

if [ -n "${NOCAP_BOARD_BACKFILL:-}" ]; then
  say "5/6 backfill: last week's turns through the same plugin hooks, clock shifted (disclosed)"
  PATH="$WORK/bin:$PATH" "$REPO/.venv/bin/python" "$REPO/demo/board_backfill.py" "$ROOTH" "$WORK"
else
  say "5/6 no backfill (set NOCAP_BOARD_BACKFILL=1 for a previous week, so trends can show)"
fi

say "6/6 the board"
HERMES_HOME="$ROOTH" hermes nocap board || true
echo
echo "dashboard: HERMES_HOME=$ROOTH hermes dashboard --port $DPORT --no-open --skip-build"
echo "work dir:  $WORK"
