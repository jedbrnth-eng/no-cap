# No Cap on Discord

## What you get

**Default (`discord_buttons: off`)** — every Discord reply with receipts gets a compact footer written for Discord:

```
**🧾 No Cap** · 🧢 2 cap · 🤔 1 no receipt
🧢 `All tests pass ✅` · call 1 `pytest -q` → says `3 failed, 41 passed in 0.02s (exit 1)`
🧢 `pushed to main` · call 2 `git push origin feat/login` → says `pushed feat/login`
-# 🧢 /cap → the agent shows receipts or takes it back
```

- The agent's words and the cited evidence sit in code spans: inert on Discord (no mentions, no markdown, no link
  previews), backticks inside them can't close the span, and secrets are masked.
- At most 1000 characters; extra receipts collapse into `+N more · /nocap all`.
- **Never split across two messages.** Hermes cuts Discord replies at 2000 characters
  (`BasePlatformAdapter.truncate_message`). Before the footer is appended, No Cap runs the whole reply through that
  same splitter (and the same table conversion); if the footer would land across a cut, it collapses to a one-line
  summary with no spaces and no newlines (non-breaking spaces), which the splitter cannot cut. Unclosed code fences in
  the reply are closed first so the footer never renders as code.

**`discord_buttons: on`** — the reply carries a one-line summary and `receipt #<id>`, and No Cap attaches to that same
message a verdict-coloured embed (red: a 🧢, amber: a 🤔, green: all 🧾) and two buttons:

- **🧢 Call cap** runs `/cap` for that session. With `allow_gateway_injection: true` the agent gets the steer and the
  next reply is re-scored, and the button turns into "Cap called". Without it, the button answers privately with the
  ready-made prompt to paste. It only works on the session's latest reply (the same rule as `/cap`).
- **🧾 Show receipts** answers privately (ephemeral) with every receipt and the cited tool calls.
- Only the person the reply answered can click (checked against the session's user id).
- Clicks are handled by custom id, not by an in-memory view, so the buttons keep working after a gateway restart.

## How it works, and what Hermes doesn't offer yet

Hermes's plugin API has no way to send an embed or buttons with a reply: `transform_llm_output` returns text and
`ctx.post_message` posts text. What it does offer is `ctx.register_platform_handler("discord", factory)`, which hands
the plugin Discord's `commands.Bot` at connect time for `add_listener` (documented in the plugin guide, "Register native
platform handlers"). No Cap uses it for three listeners:

| Listener | What it does |
|---|---|
| `on_message`, `on_raw_message_edit` | Ignores every message not written by the bot. When the bot's own reply carries a `receipt #<id>` this process issued, edits that message to add the embed and buttons (once). |
| `on_interaction` | Handles only `nocap:cap:<id>` / `nocap:show:<id>` button ids; everything else is left to Hermes and other plugins. |

The session (key, user, chat) comes from `gateway.session_context.get_session_env("HERMES_SESSION_*")`, the documented
way for plugin code to read it, at the moment the reply is checked.

Editing the bot's own message with the native client is not a documented Hermes verb, which is why it is opt-in. The
hook that would make it first-class is small: a capability-gated `ctx.platform_actions.attach_actions(platform,
chat_id, message_id, summary=…, colour=…, buttons=[…])` (Discord: embed + buttons, Telegram: inline keyboard) with a
click hook, or at least a `post_reply_delivered` hook that reports the message ids a reply was delivered as.

## Telegram

Not done: a Telegram bot never receives its own outgoing messages, so the plugin can't learn the reply's message id to
attach an inline keyboard to. Telegram keeps the generic footer.

## Known limits

- With Discord streaming turned on (`display.platforms.discord.streaming: true`; off by default in Hermes), the reply
  is cut by the stream consumer as it arrives and the split check can't see those cuts; a long footer can then still be
  split. The one-line summary (and `discord_buttons: on`) is safe either way.
- Hermes drops everything past 8 messages in one reply and posts a "Response truncated" notice instead; a footer on
  such a reply is lost with the rest of the tail.
- Tested with Hermes's real Discord adapter and real discord.py objects over a fake connection
  (`tests/test_discord_hermes.py`), not yet on a live Discord server.
