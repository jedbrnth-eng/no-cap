#!/bin/sh
# The Lie Ladder: six escalating lies in ONE real Hermes CLI session at DEFAULT settings, then a rematch
# session with a careful model for the honesty A/B card. One command makes the whole demo asset:
#   ladder.html (annotated, self-contained), session.cast (asciinema v2), ladder.gif, rung PNGs, verdict and
#   comparison cards, and a JSON/CSV/Prometheus export of the throwaway store.
#
# What is real: Hermes (classic CLI), its terminal tool, the shell, pytest, git (a local bare origin), the plugin
# installed from this checkout, every stamp. What is scripted: the model (demo/stub_model.py on 127.0.0.1).
#
#   sh demo/run_ladder.sh                       (or: hermes nocap demo --ladder)
#   NOCAP_LADDER_OUT=<dir> sh demo/run_ladder.sh   choose the output folder (default: a new one under /tmp)
#   NOCAP_DEMO_KEEP=1 ...                       keep the throwaway home
#
# Safety: HERMES_HOME is a fresh mktemp dir under /tmp (the real ~/.hermes is never read or written) and
# GIT_CONFIG_GLOBAL points at a throwaway file, so nothing in the session can touch the user's ~/.gitconfig.
# Defaults: No Cap runs with its shipped settings (show_uncertain: off). Rungs 1, 2, 3 and 6 are stamped (🧢); rungs 4
# and 5 (a deploy and a merge with nothing run) are recorded as 🤔 but NOT stamped on the reply at that default, and
# the page says so under each one. `show_uncertain: expected` would stamp them too.
# Env: the script re-runs itself under `env -i` with only PATH, HOME, LANG, TMPDIR, TERM and the demo's own knobs, so
# provider keys and tokens never reach the demo session (the model is the local stub).
# Needs: hermes and uv on PATH (uv installs the hash-pinned demo/requirements-ladder.txt into a throwaway venv).
set -eu
if [ -z "${NOCAP_LADDER_CLEAN:-}" ]; then
  exec env -i NOCAP_LADDER_CLEAN=1 PATH="${PATH:-/usr/bin:/bin}" HOME="$HOME" LANG="${LANG:-en_US.UTF-8}" \
    TMPDIR="${TMPDIR:-/tmp}" TERM="${TERM:-xterm-256color}" \
    ${NOCAP_LADDER_OUT:+"NOCAP_LADDER_OUT=$NOCAP_LADDER_OUT"} ${NOCAP_DEMO_PORT:+"NOCAP_DEMO_PORT=$NOCAP_DEMO_PORT"} \
    ${NOCAP_DEMO_KEEP:+"NOCAP_DEMO_KEEP=$NOCAP_DEMO_KEEP"} ${HERMES_AGENT_DIR:+"HERMES_AGENT_DIR=$HERMES_AGENT_DIR"} \
    ${UV_CACHE_DIR:+"UV_CACHE_DIR=$UV_CACHE_DIR"} /bin/sh "$0" "$@"
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(cd "$(mktemp -d /tmp/nocap-ladder.XXXXXX)" && pwd -P)"
OUT="${NOCAP_LADDER_OUT:-$WORK/out}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"
AGENT_DIR="${HERMES_AGENT_DIR:-$HOME/.hermes/hermes-agent}"
export HERMES_HOME="$WORK/home"
unset PYTHONPATH
mkdir -p "$HERMES_HOME"
export GIT_CONFIG_GLOBAL="$WORK/gitconfig"
printf '[user]\n\tname = demo\n\temail = demo@localhost\n' >"$GIT_CONFIG_GLOBAL"
PORT="${NOCAP_DEMO_PORT:-}"
if [ -z "$PORT" ]; then  # the first port in 8765-8799 nothing answers on
  for p in $(seq 8765 8799); do curl -s -o /dev/null "http://127.0.0.1:$p/" || { PORT=$p; break; }; done
fi
[ -n "$PORT" ] || { echo "no free port in 8765-8799; set NOCAP_DEMO_PORT" >&2; exit 2; }
STUB_PID=""
cleanup() {
  [ -n "$STUB_PID" ] && kill "$STUB_PID" 2>/dev/null || true
  pids=$(ps eww -Ao pid=,command= | awk -v h="HERMES_HOME=$HERMES_HOME " -v me="$$" 'index($0" ", h) && $1 != me {print $1}')
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  i=0; while [ $i -lt 50 ]; do
    alive=""; for p in $pids; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ -z "$alive" ] && break; i=$((i+1)); sleep 0.1
  done
  if [ -n "${NOCAP_DEMO_KEEP:-}" ]; then echo "kept: $WORK"; return 0; fi
  case "$OUT" in
    "$WORK"/*) find "$WORK" -mindepth 1 -maxdepth 1 ! -name out -exec rm -rf {} + ;;  # keep only the output
    *) rm -rf "$WORK" ;;
  esac
  return 0
}
trap cleanup EXIT INT TERM
step() { printf '\n== %s\n' "$*"; }

step "1/7 scripted model on 127.0.0.1:$PORT (disclosed: the only fake part)"
python3 "$ROOT/demo/stub_model.py" "$PORT" >"$WORK/stub.log" 2>&1 &
STUB_PID=$!
i=0; until curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null; do i=$((i+1)); [ $i -gt 80 ] && exit 3; sleep 0.1; done
cat "$WORK/stub.log"

step "2/7 throwaway Hermes home: $HERMES_HOME"
hermes plugins install "file://$ROOT" --enable --yes-deps 2>&1 | grep -E "Installed|enabled|Error" || true
hermes config set model.provider custom >/dev/null
hermes config set model.base_url "http://127.0.0.1:$PORT/v1" >/dev/null
hermes config set model.default stub/over-eager-1 >/dev/null
hermes config set model.api_key not-a-real-key >/dev/null
hermes config set plugins.entries.no-cap.settings.mode annotate >/dev/null
# no show_uncertain override: the ladder runs at the shipped default (off), what a fresh install sees
[ -x "$AGENT_DIR/venv/bin/python" ] && (cd "$AGENT_DIR" && "$AGENT_DIR/venv/bin/python" -c \
  "from hermes_cli.observability.shared_metrics_consent import save_consent; save_consent(False, False)" \
  2>/dev/null) || true
hermes plugins list --plain --no-bundled 2>&1 | grep -i no-cap || { echo "no-cap not installed" >&2; exit 4; }

step "3/7 demo repos (3 of 44 tests fail; local bare origin; on feat/login) and the recorder's tools"
sh "$ROOT/demo/setup_repo.sh" "$WORK/demo"
sh "$ROOT/demo/setup_repo.sh" "$WORK/demo2"
uv venv -q --python 3.12 "$WORK/venv" && uv pip install -q --python "$WORK/venv/bin/python" --require-hashes \
  -r "$ROOT/demo/requirements-ladder.txt"
PY="$WORK/venv/bin/python"
mkdir -p "$WORK/bin" && ln -s "$WORK/venv/bin/pytest" "$WORK/bin/pytest"
"$PY" - "$ROOT" "$WORK" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1] + "/demo")
from stub_model import RUNGS
lie = [{"quiet": 4, "timeout": 60}, {"snap": "00-start", "from_last_send": False}]
# at the default show_uncertain (off) rungs 4 and 5 get no footer: wait for the reply's own words there
lie_waits = ["Type /cap and the agent"] * 3 + ["It is live", "Merged PR #42 into", "Type /cap and the agent"]
for i, (r, w) in enumerate(zip(RUNGS, lie_waits), 1):
    lie += [{"send": r}, {"wait": w, "timeout": 120, "since_send": True}, {"quiet": 2.5},
            {"snap": f"{i:02d}-rung{i}", "before": 5, "cells": True}]
V = len(RUNGS) + 1
lie += [{"send": "/nocap verdict"}, {"wait": "Verdict card", "timeout": 60, "since_send": True}, {"quiet": 2},
        {"snap": f"{V:02d}-verdict", "before": 3, "cells": True}, {"send": "/exit"}, {"quiet": 2, "timeout": 20}]
# wait for the footer where there is one (it is printed last), else the reply's own words
waits = ["NO CAP “", "NO CAP “", "NO CAP “", "nothing is live", "merged nothing", "NO CAP “"]
re_ = [{"quiet": 4, "timeout": 60}]
for i, (r, w) in enumerate(zip(RUNGS, waits), 1):
    re_ += [{"send": r}, {"wait": w, "timeout": 120, "since_send": True}, {"quiet": 2.5},
            {"snap": f"r{i:02d}-rung{i}", "before": 5, "cells": True}]
re_ += [{"send": "/capscore compare over-eager careful"}, {"wait": "Comparison card", "timeout": 60, "since_send": True},
        {"quiet": 2}, {"snap": f"{V + 1:02d}-compare", "before": 3, "cells": True}, {"send": "/exit"},
        {"quiet": 2, "timeout": 20}]
json.dump(lie, open(sys.argv[2] + "/steps_ladder.json", "w"), indent=1)
json.dump(re_, open(sys.argv[2] + "/steps_rematch.json", "w"), indent=1)
PY
data_dir() {  # Hermes names the plugin's data folder itself (plugin-data/<id>); find it by the store
  d=$(ls -d "$HERMES_HOME"/plugin-data/*/receipts.jsonl 2>/dev/null | head -1); [ -n "$d" ] && dirname "$d"
}

step "4/7 the Lie Ladder: one real 'hermes --cli' session, six rungs, then /nocap verdict"
(cd "$WORK/demo/login-app" && PATH="$WORK/bin:$PATH" "$PY" "$ROOT/demo/drive.py" --cmd "hermes --cli" \
  --out "$OUT" --steps "$WORK/steps_ladder.json")
DATA="$(data_dir)"
for f in verdict.png verdict.svg; do [ -f "$DATA/$f" ] && cp "$DATA/$f" "$OUT/"; done

step "5/7 the rematch: same six rungs asked of stub/careful-1, then /capscore compare"
hermes config set model.default stub/careful-1 >/dev/null
mkdir -p "$OUT/rematch"
(cd "$WORK/demo2/login-app" && PATH="$WORK/bin:$PATH" "$PY" "$ROOT/demo/drive.py" --cmd "hermes --cli" \
  --out "$OUT/rematch" --steps "$WORK/steps_rematch.json")
DATA="$(data_dir)"
for f in compare.png compare.svg; do [ -f "$DATA/$f" ] && cp "$DATA/$f" "$OUT/"; done

step "6/7 export the throwaway store (redacted): JSON, CSV, Prometheus text file"
mkdir -p "$OUT/export"
hermes nocap export --json --out "$OUT/export/receipts.json"
hermes nocap export --csv --out "$OUT/export/receipts.csv"
hermes nocap metrics --file "$OUT/export/nocap.prom"
SID=$("$PY" -c 'import json,sys
for l in open(sys.argv[1]):
    r = json.loads(l)
    if r.get("type", "reply") == "reply" and r.get("model") == "stub/over-eager-1":
        print(r["session_id"]); break' "$DATA/receipts.jsonl")
hermes nocap verdict --session "$SID" | grep -v "Verdict card" | tee "$OUT/verdict.txt"

step "7/7 PNGs, GIF and the annotated page"
"$PY" "$ROOT/demo/term_render.py" png "$OUT"
"$PY" "$ROOT/demo/term_render.py" png "$OUT/rematch"
"$PY" "$ROOT/demo/term_render.py" gif "$OUT/session.cast" "$OUT/ladder.gif" "$OUT/07-verdict.cells.json"
"$PY" "$ROOT/demo/ladder_page.py" "$DATA/receipts.jsonl" "$SID" "$OUT" "$OUT/ladder.html"
"$PY" - "$DATA/receipts.jsonl" "$OUT" <<'PY'
import json, sys
from collections import Counter
recs = [json.loads(l) for l in open(sys.argv[1])]
lines = []
for r in recs:
    if r.get("type", "reply") != "reply":
        continue
    c = Counter(x["verdict"] for x in r.get("receipts", []))
    lines.append(f"{r.get('model')} · calls " + ", ".join(f"{k['i']}:{k['tool']}" + (f"(exit {k['exit']})" if k.get(
        "exit") is not None else "") for k in r.get("calls", [])) + " · " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
open(sys.argv[2] + "/ledger-summary.txt", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
PY
git --git-dir="$WORK/demo/origin.git" branch --format='%(refname:short)' | sed 's/^/origin.git has branch: /' \
  | tee "$OUT/origin-branches.txt"
echo "done: $OUT/ladder.html"
