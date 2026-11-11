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
  id reservation file `<mistakesFolder>/.ids/NNNN` (created exclusively, as ABB does). New files are 0600. No lock
  file: each write holds an `flock` on the destination folder itself (the notes folder, and the board folder for a
  board note), so two Hermes homes pointed at one vault serialize instead of losing a line. Refused: a vault that is
  missing or relative, a folder with `..`, a hidden part or an absolute path, a symlinked folder or note, and a
  profile name that isn't letters, digits, `.`, `_` or `-`. An unknown or empty profile writes nothing and gets no
  lesson (it is never filed under `default`).
- **A busy folder never holds a reply:** the lock is tried without blocking, with short pauses, for at most 120 ms per
  write in all (both folders). When another writer still holds it, that export is skipped, not waited for: the reply
  goes out, the skipped 🧢 waits in memory (at most 64) and the next write that gets the lock writes it (at most 4
  per write), and `hermes nocap obsidian sync` writes it from the store in any case (every line is idempotent by its
  receipt id). `status` shows how many are waiting. Cost: a line can land a turn late, or only at `sync` if Hermes
  exits first.
- **New files in No Cap's own data folder** (next to `receipts.jsonl`, 0600, a new randomly named temp file opened with `O_EXCL` + `os.replace`, so a file or link
  already at the temp name is never written through):
  `obsidian-lessons.json`, the lesson cache (per agent: pattern id -> 🧢 count, plus the store's inode, the byte offset
  counted up to and hashes of the store's first 256 bytes and the 64 before that offset; no claim, evidence or reply text), only with `obsidian_learn: true`, removed by
  `/nocap purge`; and `obsidian-board-<dev>-<inode>.json` per board folder, No Cap's index of the board notes it wrote
  or found (`<agent>:<pattern>` -> file name) and the next id hint, only with the board on.
- **Symlinks and the vault path:** a symlink you put in the configured `obsidian_vault` path itself (say, the vault
  lives on another disk) is allowed: it is resolved at the start of each write. From then on the vault is held by one
  descriptor, opened one path component at a time with `O_NOFOLLOW`, and every later open is relative to it. If any
  ancestor of the resolved vault is swapped for a symlink in between, that write is refused instead of following it.
  A held descriptor pins a folder, not its place in the tree, so right before each write commits (before the temp
  file, again right before `os.replace`, and before each exclusive board or `.ids` create) the path is walked again
  from `/` with `O_NOFOLLOW` and the device and inode of the vault and of every pinned folder are compared. A folder
  (or the vault) moved out of the vault, with or without a symlink left in its place, gets nothing: the write is
  refused and reported as skipped. **Residual race:** the re-check and the write are two system calls; a move in the
  microseconds between them is not caught. Closing that needs OS support (a rename bound to a verified path) that
  POSIX doesn't offer. Someone who can move folders in your vault can also edit any note in it directly.
- **What a line holds:** date, pattern id, the claim, the contradicting evidence, the receipt id. Both text fields pass
  through `redact()` in FULL before flattening or clipping (a redaction rule can need distant context, such as the
  `@` after a long URL password), then cut to 160 and Markdown-escaped. A claim can't become a link, an embed,
  HTML or a block id. No other
  reply text, no session content, no commands.
- **Known limit (same as No Cap's, docs/GUIDE.md):** a secret that sits across a parse-window edge of a tool output over
  40 KB may reach a receipt in part, unrecognised. The bridge re-runs `redact()` on every field at the vault write and
  exports nothing the local store doesn't already hold, so it doesn't make that worse, but it can't mask a fragment
  `redact()` can't recognise either.
- **New `pre_llm_call` line** (only with `obsidian_learn: true`): `[No Cap lessons for agent <profile>: ...]` plus up to
  3 of No Cap's built-in rules. Rules already live as approved Cap Coach rules are not repeated. Each turn reads
  `obsidian-lessons.json` and only the store bytes appended since it was last brought up to date, under a 15 ms CPU
  budget and an 8 MB read cap, so the turn's cost doesn't grow with the store. A new, replaced (pruned), truncated or
  rewritten store is counted again over the next turns, a step per turn: meanwhile the line uses the last complete
  counts (or, on the very first build, the counts so far, which only grow). After `/nocap purge` it is empty.
- **Reads:** the vault's `.agentbox.json` (a folder name, validated); on a 🧢 write, this agent's note and, for the
  board, one `stat` of the note the index knows, or stat probes of `.ids/NNNN` to find a free id (about 2·log2 of the
  ids skipped). Only the FIRST write to a board this Hermes home has no index for lists the folder, and only a small
  one (directory size up to 64 KiB, at most 4096 names): it reads the highest id and the first 4 KB of the notes named
  like a pattern's title (at most 32 for this pattern, 128 in all) for their `source:` key. A big board is never
  listed. For `status`, the No Cap notes and the board's names. None of it reaches the model. With the feature off,
  `pre_llm_call` reads nothing, not even No Cap's own store, and no cache file is made.
- **No network, no subprocess, no new dependency.** `open` prints a link; it doesn't launch Obsidian.

## What is not done

- An ABB note is written once per agent and pattern and never updated, so its "What happened" shows the first 🧢 only;
  the full list is in the agent's note (linked from it).
- 🤔 NO RECEIPT verdicts are not written: only direct contradictions are lessons.
- A lesson needs 2 🧢 of the same pattern; one cap is a note, not yet a rule.
- Writes require POSIX (`flock`, directory-relative operations). The bridge can stay off on Windows without breaking
  No Cap; enabled bridge writes on Windows are refused. Windows is not tested.
- Old local records without a valid profile are skipped, never guessed to belong to the current agent.
- A board note you rename or delete by hand is no longer recognised as No Cap's, so the next 🧢 on that pattern adds
  one fresh board note.
- The board index is per Hermes home. On a big board (never listed) or after the index exists, a board note for the
  same agent and pattern written by ANOTHER Hermes home (or by an older No Cap without the index) is not seen, so that
  agent can get one more board note for the pattern. Ids stay unique among `.ids` reservations (the exclusive create
  is the guard, as in ABB); a note made by hand with an `M-NNNN` id but no `.ids/NNNN` reservation can share its id.
- Lessons and the per-turn budget: on a very large store the first lesson line after a purge, prune or a new install
  can take a few turns to reach its full counts.
