# Cap Board

A leaderboard of the top cappers: which agents (Hermes profiles), models and skills make the most claims their own
turn's tool output contradicts. It is a tab in the Hermes web dashboard, next to Kanban, and the same numbers as text
from `/capscore board` or `hermes nocap board`.

![Cap Board](media/board-run/01-board.png)

## What it reads

**Scope.** By default the board shows only the profile it is asked from: the dashboard tab shows the profile the
dashboard request is scoped to, `/capscore board` the profile of the session. Other profiles are a **team view** and
need an explicit opt-in in that profile's settings:

```yaml
plugins:
  entries:
    no-cap:
      settings:
        board:
          team_profiles: all          # or a list: [alpha, beta]
```

Even with it set, only the CLI (`hermes nocap board`, `/capscore board` in a CLI session) and the dashboard tab show the
team view. `/capscore board` in a gateway chat (Telegram, Discord, Slack, ...), the TUI or Desktop always shows the
current profile, so a bot never posts another profile's claims, commands or evidence into a group chat. Hall of Cap
items carry the claim, the cited command (120 characters) and the evidence line (220 characters), redacted for secrets
but not for repo names, hostnames or paths: turn the team view on only where everyone who can open the dashboard may
see every listed profile's work. The tab footer and the text header say which scope is shown.

Every profile on the machine keeps its own No Cap store (`<HERMES_HOME>/plugin-data/agent-plugin-no-cap-4890e304/receipts.jsonl`,
or `plugin-data/no-cap/` on older builds). The board finds profiles the way Hermes does (`hermes_cli/profiles.py:481-511`):
the root home is `default`, `<root>/profiles/<name>` are the named ones, directories without an identity file
(`config.yaml`, `.env`, `SOUL.md`, `profile.yaml`, `auth.json`, `state.db`) and tombstoned profiles are skipped. It uses
only the public `hermes_constants` helpers for that, so `hermes plugins validate` reports no private imports.

Stores are opened read-only (`"rb"`), never locked, pruned or written. Only complete lines are read, so a reply being
written right now is picked up on the next poll; appends are read incrementally and a pruned or purged store is read
again in full. Unreadable lines are skipped and counted at the bottom of the tab.

In the team view, extra stores (a copied store, an arena run, another machine's export) go in `board_sources` or
`NOCAP_BOARD_SOURCES` (ignored outside the team view). A folder entry is searched at most 6 levels and 2000 folders
deep, for at most 5000 stores, and never through a symlinked folder:
`label=path` entries separated by `:`. A path can be a Hermes home, a `receipts.jsonl`, a folder searched for them, or a
glob (`arena-strict=/tmp/nocap-arena/runs/*/C`). A labelled source's label names the agent.

## Who is who

Each reply record now carries two fields written at hook time:

- `profile`: the profile the turn ran for, named like Hermes's `current_profile_name()` (`hermes_cli/profiles.py:1997`):
  a launcher pin (`HERMES_PROFILE_NAME` / `HERMES_PROFILE`) unless a per-turn home override is bound, else the profile
  owning `HERMES_HOME`. A home outside any `profiles/` folder is its own root, so it is `default`.
- `skills`: skills the turn loaded successfully with `skill_view` (a failed load of an unknown skill is not counted).
  A reply with no skill goes under `(no skill)`.

Older records without `profile` are attributed to the profile whose store they are in.

## The numbers

| Column | Meaning |
|---|---|
| Cap rate | 🧢 ÷ claims. Claims are every receipt No Cap recorded on the reply, stamped or not |
| Receipts | 🧾 ÷ claims |
| Streak | replies since the last reply that had a 🧢 |
| 7d trend | cap rate over the last 7 days minus the 7 before. ▲ = capping more. Under 2 points is flat |
| Top cap | the claim kind capped most often (`tests`, `pushed`, `merged`, ...) |

**Minimum sample.** A rate needs at least `board_min_claims` claims (default 10). Below it the row is greyed, unranked,
and shows `n=<claims>` instead of a percentage. A 100% cap rate on three claims is noise, and ranking an agent publicly on
it would be unfair. The trend uses the same rule in each 7-day window.

**Hall of Cap.** The latest 🧢 with the claim in the agent's words and the evidence that contradicted it (the command and
its output line). Strings are redacted when they are written to the store and redacted again when the board reads them.

## Live

The tab polls `GET /api/plugins/no-cap/board` every 4 seconds while it is visible and pauses when it is hidden. The
response carries a `version` built from each store's inode, size and mtime (plus the filters and the minute); sending it
back as `?v=` returns `{"unchanged": true}` when nothing moved, so a poll costs a few `stat()` calls. Rows whose reply
count changed flash once.

Why polling and not a socket: the Kanban tab tails a WebSocket (`plugins/kanban/dashboard/dist/index.js:747-794`), but a
plugin API that streams can't run in the plugin host (`hermes_cli/plugin_isolation_audit.py:195-202`: "the host bridge
buffers responses"). Polling keeps the board working under `plugins.isolation: host`, and `hermes plugins validate`
reports "dashboard backend API is served through the plugin host".

## Dashboard API used

- `dashboard/manifest.json`: `name`, `label`, `icon`, `tab.path`, `tab.position`, `entry`, `css`, `api`
  (`website/docs/user-guide/features/extending-the-dashboard.md:449-485`; discovery in
  `hermes_cli/web_server_dashboard.py:615` and `_dashboard_plugin_entry`).
- `plugin_api.py` exports a FastAPI `router`, mounted at `/api/plugins/no-cap/` (`extending-the-dashboard.md:726-750`,
  `web_server_dashboard.py:1217-1240`). Handlers are plain `def`, so FastAPI runs them in a worker thread and a cold read
  never blocks the event loop (`extending-the-dashboard.md:752-761`).
- The bundle is an IIFE on `window.__HERMES_PLUGIN_SDK__`: `React`, `hooks`, `components.Card/CardContent/Label/Select/
  SelectOption`, `fetchJSON`, `utils.cn/timeAgo` (`extending-the-dashboard.md:495-550`, `web/src/plugins/sdk.d.ts`), and
  registers with `window.__HERMES_PLUGINS__.register("no-cap", ...)`. The Select wiring is Kanban's dual
  `onValueChange`/`onChange` helper (`plugins/kanban/dashboard/dist/index.js:315-330`).
- Styling uses only the dashboard's tokens (`--color-card`, `--color-border`, `--color-muted-foreground`,
  `--color-destructive`, `--color-success`, `--color-warning`, `--color-ring`, `--radius`, `--font-mono`), like the
  Kanban stylesheet, so every dashboard theme reskins it (`extending-the-dashboard.md:789-814`).

## Proof

`sh demo/run_board_demo.sh` builds a throwaway Hermes root under `/tmp` with three real profiles (`hermes profile create
--no-alias`), installs this checkout into each, and runs real `hermes chat` turns in each profile's own demo repo:
real `pytest`, real `git push` to a local bare origin, real `skill_view`. Disclosed scripted parts: the models
(`demo/board_stub_model.py`, three personas on 127.0.0.1) and, with `NOCAP_BOARD_BACKFILL=1`, last week's turns
(`demo/board_backfill.py`), which go through the installed plugin's own hooks with real command output and the clock
shifted 8-12 days back so the trend has a previous week. No store line is written by hand.

Screenshots (`docs/media/board-run/`, real dashboard, real browser, throwaway root):

| File | What it shows |
|---|---|
| `01-board.png` | the board: alpha, beta, gamma from real `hermes chat` turns (+ disclosed backfill), and two real-model arena stores (qwen3-4b, partial) greyed under the min-sample rule |
| `02-live-before.png`, `03-live-flash.png`, `04-live-after.png`, `live-poll-log.txt` | live refresh: two more real gamma turns land while the tab is open; the row flashes and its counts move with no reload |
| `05-filter-skill-github.png` | filtered to the `github` skill: one agent, n=7, so no rate and no rank |
| `06-skills-view.png` | the Skills view |
| `07-arena-real-model-partial.png` | filtered to the real model (qwen3-4b arena runs, 7 replies, 5 claims so far): nothing ranked yet |
| `capscore-board.txt` | `hermes nocap board` on the same root |

Performance: 10,000 records (13 MB) from three profiles build the whole board in about 70 ms of CPU cold on a quiet
machine (up to ~170 ms with the load average above 60), and about 10 ms warm thanks to the incremental cache:
`tests/test_board.py::test_10k_records_under_200ms` (best of five cold reads in CPU time, with the ReDoS test's machine
calibration: the 200 ms budget scales by how much slower the machine is right now, capped at 4x, and the scale is
printed).
