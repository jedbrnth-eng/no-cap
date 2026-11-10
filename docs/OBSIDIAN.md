# Obsidian lessons: per-agent 🧢 notes, and agents that learn from their own caps

Opt-in. Off by default: with `obsidian_vault` empty, No Cap reads and writes nothing in any vault.

When No Cap stamps a claim 🧢 CAP (the tool output in the same turn says the opposite), the bridge:

1. appends one line to that agent's note, `<vault>/No Cap/<profile>.md`: the date, the pattern id, the claim and the
   contradicting evidence (both redacted, one line, at most 160 characters, Markdown-escaped) and a block id
   `^nc-<receipt id>`, so the same receipt is never written twice;
2. the first time an agent caps on a pattern, adds ONE note to the Agent Black Box (ABB) Obsidian plugin's
   mistakes board in ABB's own format (`M-NNNN <title>.md`, `agent:` = the profile, `source: "nocap:<profile>:<pattern>"`,
   Prevention rule = No Cap's built-in rule for that pattern). ABB's board, `abb mistake list` and
   `abb mistake brief --agent <profile>` show it like any other lesson. No Cap never edits that note again: its status,
   fix and verification are yours;
3. with `obsidian_learn: true`, starts each of that agent's turns with a labelled line holding up to 3 built-in rules for
   the patterns it was stamped 🧢 on at least twice. Agent A's caps never reach agent B's prompt.

The lesson line is built from No Cap's local receipt store and its built-in rule text only. Nothing is read from the
vault into the prompt: a vault note can be edited by anyone, the agent included, so its prose would be an injection path.

## Setup in 3 steps

```sh
# 1. point No Cap at an existing vault (absolute path; No Cap never creates a vault)
hermes config set plugins.entries.no-cap.settings.obsidian_vault "/path/to/your vault"
# 2. optional: let each agent learn from its own repeated caps
hermes config set plugins.entries.no-cap.settings.obsidian_learn true
# 3. check it, and backfill the caps already in the store
hermes nocap obsidian status
hermes nocap obsidian sync
```

Restart running sessions (hooks load at session start). `hermes nocap obsidian open` prints this agent's note path and
an `obsidian://` link (it runs nothing). `hermes nocap doctor` shows the bridge in one line.

| Setting | Default | What it does |
|---|---|---|
| `obsidian_vault` | `""` (off) | Absolute path of an existing vault. Empty = the whole feature is off. |
| `obsidian_folder` | `No Cap` | Vault-relative folder for the per-agent notes. No `..`, no leading dot, no absolute path. |
| `obsidian_board` | `auto` | ABB board notes: `auto` = only when the vault has `.agentbox.json` or an `Agent Black Box` folder; `on`; `off`. The folder comes from ABB's `.agentbox.json` (`mistakesFolder`), else `Agent Black Box/Mistakes`. |
| `obsidian_learn` | `false` | The per-agent lesson line in `pre_llm_call` (needs `obsidian_vault` too). |

## Disclosure (what changes when you turn it on)

- **New file-write path, inside the vault you name only:** `<vault>/<obsidian_folder>/<profile>.md` (rewritten through a
  temp file in the same folder and `os.replace`), and for the board `<mistakesFolder>/M-NNNN <title>.md` plus an empty
  id reservation file `<mistakesFolder>/.ids/NNNN` (created exclusively, as ABB does). New files are 0600. A lock file
  `obsidian.lock` lives in No Cap's own data folder, not in the vault. Refused: a vault that is missing or relative, a
  folder with `..`, a hidden part or an absolute path, a symlinked folder or note (every open uses `O_NOFOLLOW` and the
  resolved path must stay inside the vault), and a profile name that isn't letters, digits, `.`, `_` or `-`.
- **What a line holds:** date, pattern id, the claim, the contradicting evidence, the receipt id. Both text fields pass
  through `redact()` (cut to 2,000 characters first, dropping a half word at the cut so a split secret can't slip past,
  then cut to 160) and are Markdown-escaped, so a claim can't become a link, an embed, HTML or a block id. No other
  reply text, no session content, no commands.
- **New `pre_llm_call` line** (only with `obsidian_learn: true`): `[No Cap lessons for agent <profile>: ...]` plus up to
  3 of No Cap's built-in rules. Rules already live as approved Cap Coach rules are not repeated.
- **Reads:** the vault's `.agentbox.json` (a folder name, validated), and for `status`/`sync` the No Cap notes and the
  first 4 KB of each board note (to count lines and find an existing `source:` key). None of it reaches the model.
- **No network, no subprocess, no new dependency.** `open` prints a link; it doesn't launch Obsidian.

## What is not done

- An ABB note is written once per agent and pattern and never updated, so its "What happened" shows the first 🧢 only;
  the full list is in the agent's note (linked from it).
- 🤔 NO RECEIPT verdicts are not written: only direct contradictions are lessons.
- A lesson needs 2 🧢 of the same pattern; one cap is a note, not yet a rule.
