"""Discord-native receipts.

Two layers, both built only on documented Hermes plugin surfaces (see docs/DISCORD.md for the file:line research):

1. **Footer** (always, when ``platform == "discord"``). Discord markdown, emoji stamps, the agent's words and the cited
   evidence in code spans (inert: no mentions, no markdown, no link unfurls), at most ``FOOTER_MAX`` characters, overflow
   collapsed into ``+N more``. Before the footer goes out, the whole reply is run through Hermes's own Discord splitter
   (``BasePlatformAdapter.truncate_message`` at 2000 chars); if the footer would be cut across two messages it collapses
   to a one-line summary with no spaces and no newlines (NBSP), which the splitter cannot cut. Append-only.

2. **Embed + buttons** (opt-in, ``discord_buttons: on``). Hermes has no API to attach an embed or components to a reply
   (``transform_llm_output`` returns text; ``post_message`` is text only). So the footer becomes the one-line summary
   plus ``receipt #<id>``, and a listener on the discord.py ``Bot`` that ``ctx.register_platform_handler("discord", …)``
   hands over sees that reply (the bot's own message) and edits it to add a verdict-coloured embed and two buttons.
   Clicks arrive on ``on_interaction`` (custom ids ``nocap:cap:<id>`` / ``nocap:show:<id>``), so they keep working
   after a gateway restart. Only the user the reply answered may click. 🧢 Call cap runs /cap for that session
   (``ctx.inject_message`` with the session key, gated by ``allow_gateway_injection``); when Hermes refuses the
   injection the button answers, privately, with the ready-made prompt to paste.

Fail open everywhere: a listener that raises is logged and the reply stays as it was.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..evidence import redact
from ..render import EMOJI, ORDER, claim_text, counts, dedupe
from ..verdict import CAP, NO_CAP, NO_RECEIPT

logger = logging.getLogger("hermes_plugins.no_cap")

PLATFORM = "discord"
DISCORD_LIMIT = 2000           # Discord's per-message cap (Hermes: DiscordAdapter.MAX_MESSAGE_LENGTH)
MAX_SPLIT_MESSAGES = 8         # Hermes replaces chunks past this with a notice (DiscordAdapter.MAX_SPLIT_MESSAGES)
FOOTER_MAX = 1000
MAX_LINES = 8
EMBED_MAX = 3500               # embed description budget (Discord allows 4096)
SHOW_MAX = 1900                # ephemeral "Show receipts" answer (Discord allows 2000)
TOKENS_FILE = "discord_receipts.json"
MAX_TOKENS = 500
NBSP = "\u00a0"
TOKEN_RE = re.compile(r"receipt" + NBSP + r"#([0-9a-f]{8})\b")
COLOUR = {CAP: 0xE5484D, NO_RECEIPT: 0xF5A524, NO_CAP: 0x30A46C}
WORD = {CAP: "cap", NO_RECEIPT: "no receipt", NO_CAP: "no cap"}
_INDICATOR = re.compile(r" \(\d+/\d+\)$")
_MD = re.compile(r"([\\*_~|`<>\[\]])")


def is_discord(platform: Any) -> bool:
    return isinstance(platform, str) and platform.strip().lower() == PLATFORM


# ---- text helpers -------------------------------------------------------------------------------------------------
def _short(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def code(s: Any, n: int) -> str:
    """One inline code span; it can't be closed early, newlines are folded, secrets masked. A lone backtick inside
    (a command's `date`) stays a real backtick: the span is then fenced with two backticks and padded, as Discord
    markdown allows. Only a run of two or more, which could close that span, becomes the lookalike ˋ."""
    s = _short(redact(str(s or "")), n)
    if not s.strip():
        return ""
    if "`" not in s:
        return f"`{s}`"
    s = re.sub(r"`{2,}", lambda m: "ˋ" * len(m.group(0)), s)
    return f"`` {s} ``"


_MD_EMPHASIS = re.compile(r"`+|\*\*|__")


def claim_code(s: Any, n: int) -> str:
    """The agent's own words in a code span. Its markdown (`code`, **bold**) is formatting, not content: dropped, so
    the footer reads `passed on abc1234`, not `passed on ˋabc1234ˋ`."""
    return code(" ".join(_MD_EMPHASIS.sub("", str(s or "")).split()), n)


def plain(s: Any, n: int = 200) -> str:
    """Text outside code spans: markdown escaped, mentions defused (a zero-width space after @)."""
    s = _short(str(s or ""), n)
    return _MD.sub(r"\\\1", s).replace("@", "@\u200b")


_QUOTED = re.compile(r"“([^”]*)”")


def _prose(line: str, n: int = 180) -> str:
    """An engine line (re-score, note): the agent's quoted words go in a code span, the rest is escaped."""
    out, pos = [], 0
    for m in _QUOTED.finditer(line):
        out.append(plain(line[pos:m.start()], n))
        out.append(claim_code(m.group(1), 60))
        pos = m.end()
    out.append(plain(line[pos:], n))
    return "".join(out)


# ---- the footer ---------------------------------------------------------------------------------------------------
def receipt_line(r: Dict[str, Any], strict: bool = False, wide: bool = False) -> str:
    v = r["verdict"]
    n = 2 if wide else 1
    head = EMOJI[v] + (" Unverified" if strict and v == CAP else "")
    parts = [head + " " + (claim_code(claim_text(r), 70 * n) or "`(claim)`")]
    if r.get("cite") is not None:
        where = f" · call {plain(r['cite'], 8)}"
        what = r.get("cmd") or r.get("tool")
        if what:
            where += " " + code(what, 45 * n)
        detail = r.get("quote") or r.get("why") or ""
        if v == NO_RECEIPT and r.get("why"):
            detail = r["why"]
        if detail:
            where += " → " + ("says " if v == CAP else "") + code(detail, 70 * n)
        parts.append(where)
    else:
        parts.append(" · " + plain(r.get("why") or "no tool call backs it", 80 * n))
    if r.get("verified"):
        parts.append(" · ✅ " + code(r["verified"], 60 * n))
    return "".join(parts)


def _header(receipts: List[Dict[str, Any]], streak: Optional[int], mode: str, sep: str = " · ") -> str:
    c = counts(receipts)
    head = ["**🧾 No Cap**"]
    for v in (CAP, NO_RECEIPT, NO_CAP):
        if c[v]:
            head.append(f"{EMOJI[v]} {c[v]} {WORD[v]}")
    if streak and not c[CAP]:
        head.append(f"🔥 {int(streak)} no cap in a row")
    if mode == "strict":
        head.append("strict")
    return sep.join(head)


def _open(receipts: List[Dict[str, Any]]) -> bool:
    return any(r["verdict"] in (CAP, NO_RECEIPT) for r in receipts)


def footer(receipts: List[Dict[str, Any]], rescore: Optional[List[str]] = None, streak: Optional[int] = None,
           notes: Optional[List[str]] = None, mode: str = "annotate", budget: int = FOOTER_MAX) -> str:
    receipts = sorted(dedupe(receipts), key=lambda r: ORDER[r["verdict"]])
    lines = [_header(receipts, streak, mode)]
    lines += [_prose(x) for x in (rescore or [])[:4]]
    lines += [_prose(x) for x in (notes or [])[:2]]
    tail = "-# 🧢 /cap → the agent shows receipts or takes it back" if _open(receipts) else ""
    body = [receipt_line(r, strict=(mode == "strict")) for r in receipts]

    def size(extra: List[str]) -> int:
        return len("\n".join(lines + extra + ([tail] if tail else [])))

    shown: List[str] = []
    for i, line in enumerate(body):
        rest = len(body) - i - 1
        more = [f"+{rest} more · /nocap all"] if rest else []
        if len(shown) >= MAX_LINES or size(shown + [line] + more) > budget:
            break
        shown.append(line)
    if len(shown) < len(body):
        shown.append(f"+{len(body) - len(shown)} more · /nocap all")
    out = "\n".join(lines + shown + ([tail] if tail else []))
    if len(out) > budget:  # only reachable with very long re-score/note lines: keep the head, cut the rest
        out = out[: budget - 1] + "…"
    return out


def one_liner(receipts: List[Dict[str, Any]], rescore: Optional[List[str]] = None, streak: Optional[int] = None,
              notes: Optional[List[str]] = None, mode: str = "annotate", token: Optional[str] = None) -> str:
    """The split-proof summary: no newline and no plain space, so Hermes's splitter can only cut before it."""
    receipts = dedupe(receipts)
    parts = [_header(receipts, streak, mode)]
    if rescore:
        parts.append(f"🔁 {len(rescore)} re-scored")
    if notes:
        parts.append(f"⚠️ {len(notes)} warning(s): /nocap")
    if token:
        parts.append(f"receipt #{token}")
    else:
        parts.append("/nocap for receipts" + (" · /cap to call it" if _open(receipts) else ""))
    return " · ".join(parts).replace(" ", NBSP)


# ---- split guard --------------------------------------------------------------------------------------------------
def hermes_splitter() -> Optional[Callable[[str], List[str]]]:
    """Hermes's own Discord send path: format_message (tables → bullets), then truncate_message at 2000. None outside
    a Hermes process (the CLI tests), where compose() falls back to "fits in one message or use the one-liner"."""
    try:
        from gateway.platforms.base import BasePlatformAdapter
    except Exception:
        return None
    try:
        from gateway.platforms.helpers import convert_table_to_bullets
    except Exception:
        def convert_table_to_bullets(content: str) -> str:
            return content
    return lambda text: BasePlatformAdapter.truncate_message(convert_table_to_bullets(text), DISCORD_LIMIT)


def _intact(text: str, tail: str, split: Optional[Callable[[str], List[str]]]) -> bool:
    if split is None:
        return len(text) <= DISCORD_LIMIT - 10
    try:
        chunks = split(text)
    except Exception:
        return len(text) <= DISCORD_LIMIT - 10
    if len(chunks) > MAX_SPLIT_MESSAGES:
        return False
    return any(tail in _INDICATOR.sub("", c) for c in chunks)


def _sep(text: str) -> str:
    fences = sum(1 for ln in text.splitlines() if ln.lstrip().startswith("```"))
    return "\n```\n\n" if fences % 2 else "\n\n"


_DEFAULT = object()


def compose(text: str, receipts: List[Dict[str, Any]], mode: str, rescore: Optional[List[str]] = None,
            streak: Optional[int] = None, notes: Optional[List[str]] = None, token: Optional[str] = None,
            split: Any = _DEFAULT) -> Optional[str]:
    if mode == "quiet" or (not receipts and not rescore and not notes):
        return None
    sep = _sep(text)
    small = one_liner(receipts, rescore, streak, notes, mode, token)
    if token:
        return text + sep + small
    full = footer(receipts, rescore, streak, notes, mode)
    splitter = hermes_splitter() if split is _DEFAULT else split
    if _intact(text + sep + full, full, splitter):
        return text + sep + full
    return text + sep + small


# ---- receipt ids (buttons mode) -----------------------------------------------------------------------------------
def _session_env() -> Dict[str, str]:
    """The calling chat, read the documented way (plugins guide: get_session_env, not os.environ)."""
    try:
        from gateway.session_context import get_session_env
    except Exception:
        return {}
    keys = ("KEY", "USER_ID", "CHAT_ID", "THREAD_ID")
    return {f"HERMES_SESSION_{k}": get_session_env(f"HERMES_SESSION_{k}", "") for k in keys}


class DiscordSurface:
    """Per-plugin-instance state: the live bot (if any), the receipt ids this process issued."""

    def __init__(self, engine: Any, setting: Callable[[str, Any], Any], data_dir: Callable[[], Path],
                 session_env: Callable[[], Dict[str, str]] = _session_env):
        self.engine = engine
        self.setting = setting
        self.data_dir = data_dir
        self.session_env = session_env
        self._bot: Any = None
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # -- settings / state
    def buttons_on(self) -> bool:
        try:
            v = self.setting("discord_buttons", "off")
        except Exception:
            return False
        return str(v).strip().lower() in ("on", "true", "1", "yes")

    def live(self) -> bool:
        bot = self._bot
        if bot is None or getattr(bot, "user", None) is None:
            return False
        try:
            return not bot.is_closed()
        except Exception:
            return False

    @property
    def path(self) -> Path:
        return Path(self.data_dir()) / TOKENS_FILE

    # -- transform_llm_output
    def compose(self, text: str, receipts: List[Dict[str, Any]], mode: str, rescore: Optional[List[str]] = None,
                streak: Optional[int] = None, notes: Optional[List[str]] = None, session_id: str = "",
                turn_id: str = "") -> Optional[str]:
        if mode == "quiet" or (not receipts and not rescore and not notes):
            return None
        token = None
        if receipts and session_id and self.buttons_on() and self.live():
            token = self._issue(session_id, turn_id, receipts, rescore, notes, mode)
        return compose(text, receipts, mode, rescore, streak, notes, token=token)

    def _issue(self, session_id: str, turn_id: str, receipts: List[Dict[str, Any]], rescore: Optional[List[str]],
               notes: Optional[List[str]], mode: str) -> Optional[str]:
        env = self.session_env() or {}
        entry = {"session_id": session_id, "turn_id": turn_id, "ts": time.time(),
                 "session_key": env.get("HERMES_SESSION_KEY", ""), "user_id": env.get("HERMES_SESSION_USER_ID", ""),
                 "chat_id": env.get("HERMES_SESSION_CHAT_ID", ""), "thread_id": env.get("HERMES_SESSION_THREAD_ID", "")}
        with self._lock:
            token = secrets.token_hex(4)
            while token in self._mem:
                token = secrets.token_hex(4)
            self._mem[token] = dict(entry, receipts=list(receipts), rescore=list(rescore or []),
                                    notes=list(notes or []), mode=mode)
            while len(self._mem) > MAX_TOKENS:
                self._mem.pop(next(iter(self._mem)))
            try:
                self._save_locked(token, entry)
            except Exception as exc:  # the footer still goes out; only a restart loses the buttons
                logger.warning("no-cap: couldn't save the Discord receipt id: %s", exc)
        return token

    def _load_locked(self) -> Dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_locked(self, token: str, entry: Dict[str, Any]) -> None:
        from ..store import _open_private, _private_dir, _scrub
        data = self._load_locked()
        data[token] = _scrub(entry)
        if len(data) > MAX_TOKENS:
            data = dict(sorted(data.items(), key=lambda kv: float((kv[1] or {}).get("ts", 0) or 0))[-MAX_TOKENS:])
        p = self.path
        _private_dir(p.parent)
        tmp = p.with_suffix(".tmp")
        with _open_private(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC) as fh:
            json.dump(data, fh)
        os.replace(tmp, p)

    def _update(self, token: str, **fields: Any) -> None:
        with self._lock:
            if token in self._mem:
                self._mem[token].update(fields)
            data = self._load_locked()
            if token in data:
                try:
                    self._save_locked(token, dict(data[token], **fields))
                except Exception as exc:
                    logger.debug("no-cap: couldn't update the Discord receipt id: %s", exc)

    def lookup(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if token in self._mem:
                return self._mem[token]
            entry = self._load_locked().get(token)
            return entry if isinstance(entry, dict) else None

    # -- register_platform_handler("discord", wire)
    def wire(self, bot: Any, adapter: Any = None) -> None:
        """Called by Hermes's Discord adapter at connect (and again after a client rebuild) with the discord.py Bot."""
        self._bot = bot
        bot.add_listener(self._on_message, "on_message")
        bot.add_listener(self._on_raw_edit, "on_raw_message_edit")
        bot.add_listener(self._on_interaction, "on_interaction")

    async def _on_message(self, message: Any) -> None:
        try:
            await self.attach(getattr(getattr(message, "channel", None), "id", None), getattr(message, "id", None),
                              getattr(message, "content", "") or "", getattr(getattr(message, "author", None), "id", None))
        except Exception as exc:
            logger.warning("no-cap: Discord attach failed open: %s", exc, exc_info=True)

    async def _on_raw_edit(self, payload: Any) -> None:
        try:
            data = getattr(payload, "data", None) or {}
            content = data.get("content")
            if not isinstance(content, str):
                return
            author = (data.get("author") or {}).get("id")
            await self.attach(getattr(payload, "channel_id", None), getattr(payload, "message_id", None), content, author)
        except Exception as exc:
            logger.warning("no-cap: Discord attach failed open: %s", exc, exc_info=True)

    async def attach(self, channel_id: Any, message_id: Any, content: str, author_id: Any) -> bool:
        """The bot just posted (or finished editing) a reply carrying one of our receipt ids: add the embed + buttons."""
        bot = self._bot
        me = getattr(getattr(bot, "user", None), "id", None)
        if bot is None or me is None or str(author_id) != str(me) or channel_id is None or message_id is None:
            return False
        found = TOKEN_RE.findall(content or "")
        if not found:
            return False
        token = found[-1]  # the footer is last; an id the model echoed earlier in the text never wins
        with self._lock:
            entry = self._mem.get(token)
            if entry is None or entry.get("attached"):
                return False
            if entry.get("chat_id") and str(channel_id) not in (entry["chat_id"], entry.get("thread_id")):
                return False
            entry["attached"] = True
        import discord  # the gateway that called wire() has it
        embed = build_embed(discord, token, entry)
        view = build_view(discord, token, open_=_open(entry["receipts"]))
        target = bot.get_partial_messageable(int(channel_id)).get_partial_message(int(message_id))
        await target.edit(embed=embed, view=view)
        return True

    async def _on_interaction(self, interaction: Any) -> None:
        data = getattr(interaction, "data", None) or {}
        custom_id = str(data.get("custom_id") or "") if isinstance(data, dict) else ""
        if not custom_id.startswith("nocap:"):
            return  # not ours: core views and other plugins handle their own components
        try:
            await self.click(interaction, custom_id)
        except Exception as exc:
            logger.warning("no-cap: Discord button failed open: %s", exc, exc_info=True)
            await _reply(interaction, "No Cap hit an error and changed nothing. `/nocap` and `/cap` still work.")

    async def click(self, interaction: Any, custom_id: str) -> str:
        parts = custom_id.split(":")
        action, token = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
        entry = self.lookup(token) if re.fullmatch(r"[0-9a-f]{8}", token or "") else None
        if entry is None or action not in ("cap", "show"):
            return await _reply(interaction, "🧾 This receipt is too old for buttons. Type `/nocap` or `/cap`.")
        uid = str(getattr(getattr(interaction, "user", None), "id", "") or "")
        if not entry.get("user_id") or uid != str(entry["user_id"]):
            return await _reply(interaction, "🧾 Only the person this reply answered can use these buttons.")
        if action == "show":
            return await _reply(interaction, self.show_text(token, entry))
        last = self.engine.store.last(entry["session_id"])
        if last is not None and last.get("turn_id") and entry.get("turn_id") and last["turn_id"] != entry["turn_id"]:
            return await _reply(interaction, "🧢 This isn't the session's latest reply any more; /cap checks the "
                                             "latest one. Type `/cap` if that's what you want.")
        if entry.get("capped"):
            return await _reply(interaction, "🧢 Cap was already called on this reply.")
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception as exc:
            logger.debug("no-cap: defer failed; answering directly: %s", exc)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, functools.partial(
            self.engine.cap, "", session_id=entry["session_id"], session_key=entry.get("session_key") or ""))
        text = paste_ready(text or "")
        if "Cap called on" in text:
            self._update(token, capped=True)
            try:
                import discord
                await interaction.message.edit(view=build_view(discord, token, open_=False, called=True))
            except Exception as exc:
                logger.debug("no-cap: couldn't disable the Call cap button: %s", exc)
        return await _reply(interaction, text)

    def show_text(self, token: str, entry: Dict[str, Any]) -> str:
        rec = None
        for r in reversed(self.engine.store.records()):
            if r.get("type") == "reply" and r.get("session_id") == entry["session_id"] \
                    and r.get("turn_id") == entry.get("turn_id"):
                rec = r
                break
        receipts = (rec or {}).get("receipts") or entry.get("receipts") or []
        lines = [f"**🧾 Receipts** · receipt #{token}"]
        for r in sorted(receipts, key=lambda r: ORDER.get(r.get("verdict"), 3)):
            lines.append(receipt_line(r, strict=False, wide=True) + (" · _not stamped: unsure_" if r.get("hidden") else ""))
        calls = (rec or {}).get("calls") or []
        ledger = (rec or {}).get("ledger") or {}
        if calls or ledger:
            lines.append(f"**Cited calls** · {int(ledger.get('n', len(calls)) or 0)} tool call(s) this turn")
            for c in calls[-10:]:
                ex = f" exit {plain(c['exit'], 6)}" if c.get("exit") is not None else ""
                lines.append(f"call {plain(c.get('i'), 6)} {code(c.get('tool'), 30)}{ex} {code(c.get('cmd'), 120)}".rstrip())
        out = []
        for ln in lines:
            if len("\n".join(out + [ln])) > SHOW_MAX - 40:
                out.append(f"+{len(lines) - len(out)} more · `/nocap all`")
                break
            out.append(ln)
        return "\n".join(out)


def paste_ready(text: str) -> str:
    """engine.cap's refusal text ends with the steer to paste: put it in a code block so it copies cleanly."""
    marker = "\n\n[No Cap]"
    if marker in text:
        head, steer = text.split(marker, 1)
        text = head + "\n```text\n[No Cap]" + steer.replace("```", "ˋˋˋ") + "\n```"
    if len(text) > SHOW_MAX:
        text = text[: SHOW_MAX - 5] + "…"
        if text.count("```") % 2:
            text += "\n```"
    return text


async def _reply(interaction: Any, text: str) -> str:
    """Answer a click privately (ephemeral), as a followup when the click was already deferred."""
    kwargs: Dict[str, Any] = {"ephemeral": True}
    try:
        import discord
        kwargs["allowed_mentions"] = discord.AllowedMentions.none()
    except Exception as exc:
        logger.debug("no-cap: discord.AllowedMentions unavailable: %s", exc)
    done = False
    try:
        done = bool(interaction.response.is_done())
    except Exception as exc:
        logger.debug("no-cap: interaction state unknown: %s", exc)
    if done:
        await interaction.followup.send(text, **kwargs)
    else:
        await interaction.response.send_message(text, **kwargs)
    return text


# ---- discord.py objects (built lazily: discord.py is only importable inside the gateway) ------------------------
def build_embed(discord: Any, token: str, entry: Dict[str, Any]) -> Any:
    receipts = sorted(dedupe(entry.get("receipts") or []), key=lambda r: ORDER[r["verdict"]])
    c = counts(receipts)
    verdict = CAP if c[CAP] else NO_RECEIPT if c[NO_RECEIPT] else NO_CAP
    title = _header(receipts, None, entry.get("mode") or "annotate").replace("**", "")
    lines = [_prose(x) for x in (entry.get("rescore") or [])[:4]] + [_prose(x) for x in (entry.get("notes") or [])[:2]]
    body = [receipt_line(r, strict=(entry.get("mode") == "strict")) for r in receipts]
    shown: List[str] = []
    for i, line in enumerate(body):
        if len("\n".join(lines + shown + [line])) > EMBED_MAX - 40:
            shown.append(f"+{len(body) - i} more · /nocap all")
            break
        shown.append(line)
    embed = discord.Embed(title=title[:256], description="\n".join(lines + shown)[:4096],
                          colour=discord.Colour(COLOUR[verdict]))
    hint = "🧢 Call cap: the agent shows receipts or takes it back · " if _open(receipts) else ""
    embed.set_footer(text=f"{hint}receipt #{token}")
    return embed


def build_view(discord: Any, token: str, open_: bool, called: bool = False) -> Any:
    # Clicks are handled by the on_interaction listener, not by this View's callbacks, so the buttons keep working
    # after the View times out or the gateway restarts; the short timeout only frees discord.py's view store.
    view = discord.ui.View(timeout=30)
    view.add_item(discord.ui.Button(label="Cap called" if called else "Call cap", emoji="🧢",
                                    style=discord.ButtonStyle.danger, custom_id=f"nocap:cap:{token}",
                                    disabled=not open_))
    view.add_item(discord.ui.Button(label="Show receipts", emoji="🧾", style=discord.ButtonStyle.secondary,
                                    custom_id=f"nocap:show:{token}"))
    return view
