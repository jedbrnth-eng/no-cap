"""No Cap: receipts for agent claims.

Two hooks and three slash commands, public plugin surfaces only:
  post_tool_call        → record an evidence ledger for the turn (facts only, raw output never stored)
  transform_llm_output  → check the final reply's claims against that ledger, append the receipts
  /cap /capscore /nocap → call cap on the last reply, honesty leaderboard, receipts and store admin
  dashboard/            → the Cap Board tab: this profile's store ranked live (team view opt-in), read-only
  hermes nocap ...      → the same from a terminal

Fail open by design: if anything in here raises, the reply goes out unchanged and the error is logged.
A missed flag costs less than a broken reply.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .nocap.engine import Engine
from .nocap.surfaces.discord import DiscordSurface

logger = logging.getLogger("hermes_plugins.no_cap")

__version__ = "0.1.0"


def _broadcast(event: str, payload: dict) -> None:
    """Tell a connected Desktop window that receipts changed (documented public helper; a logged no-op when no
    Desktop client is attached to this process)."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
    except Exception:
        return
    broadcast_plugin_event("no-cap", event, payload)


def _make_engine(ctx: Any) -> Engine:
    def setting(key: str, default: Any = None) -> Any:
        try:
            value = ctx.get_config(key, default)
        except Exception:
            return default
        return default if value is None else value

    def data_dir() -> Path:
        return Path(ctx.state.data_dir)

    def inject(text: str, session_key: str = "") -> bool:
        if session_key:
            return bool(ctx.inject_message(text, role="user", session_key=session_key))
        return bool(ctx.inject_message(text, role="user"))

    def cwd() -> str:
        fn = getattr(ctx, "session_cwd", None)
        return fn() if callable(fn) else ""

    def home() -> Path:
        try:
            from hermes_constants import get_hermes_home  # documented public module
            return Path(get_hermes_home())
        except Exception:
            return data_dir().parents[1]

    def config() -> dict:
        try:
            from hermes_cli.config import load_config_readonly  # documented public module
            return load_config_readonly() or {}
        except Exception:
            return {}

    def entry() -> dict:
        plugins = config().get("plugins") or {}
        return ((plugins.get("entries") or {}).get("no-cap")) or {}

    def enabled(name: str):
        plugins = config().get("plugins") or {}
        if name in (plugins.get("disabled") or []):
            return False
        on = plugins.get("enabled")
        return (name in on) if isinstance(on, list) else None

    return Engine(data_dir, setting, inject=inject, cwd=cwd, home=home, entry=entry, enabled=enabled,
                  broadcast=lambda event, payload: _broadcast(event, payload))


def register(ctx: Any) -> None:
    engine = _make_engine(ctx)
    # Discord: its own compact footer always; the embed + buttons only with discord_buttons: on, through the discord.py
    # Bot that the documented register_platform_handler hands over (nocap/surfaces/discord.py, docs/DISCORD.md).
    discord_surface = DiscordSurface(engine, engine.setting, engine.data_dir)
    engine.surfaces["discord"] = discord_surface.compose
    if callable(getattr(ctx, "register_platform_handler", None)):
        try:
            ctx.register_platform_handler("discord", discord_surface.wire)
        except Exception as exc:  # an older Hermes: the text footer still works
            logger.warning("no-cap: Discord buttons unavailable: %s", exc)

    def on_tool(**kwargs: Any) -> None:
        try:
            engine.on_tool(**kwargs)
        except Exception as exc:  # fail open: never disturb the tool loop
            logger.warning("no-cap: post_tool_call failed open: %s", exc, exc_info=True)

    def on_reply(**kwargs: Any) -> Optional[str]:
        try:
            return engine.on_reply(**kwargs)
        except Exception as exc:  # fail open: the reply goes out unchanged
            logger.warning("no-cap: transform_llm_output failed open, reply unchanged: %s", exc, exc_info=True)
            return None

    def command(fn, wants_key=False, wants_platform=False):
        def handler(raw_args: str = "", session_id: str = "", session_key: str = "", platform: str = "",
                    **_: Any) -> str:
            try:
                if wants_key:
                    return fn(raw_args or "", session_id=session_id or "", session_key=session_key or "")
                if wants_platform:  # Hermes passes the surface (cli, tui, desktop, telegram, ...) to the handler
                    return fn(raw_args or "", session_id=session_id or "", platform=str(platform or ""))
                return fn(raw_args or "", session_id=session_id or "")
            except Exception as exc:
                logger.warning("no-cap: command failed: %s", exc, exc_info=True)
                return f"no-cap hit an error and changed nothing: {exc}"
        return handler

    ctx.register_hook("post_tool_call", on_tool)
    ctx.register_hook("transform_llm_output", on_reply)
    def on_verify(**kwargs: Any) -> Optional[dict]:
        try:
            return engine.on_verify(**kwargs)
        except Exception as exc:  # fail open: the turn finishes normally
            logger.warning("no-cap: pre_verify failed open: %s", exc, exc_info=True)
            return None

    ctx.register_hook("pre_verify", on_verify)
    ctx.register_command("cap", handler=command(engine.cap, wants_key=True),
                         description="Call cap on the last reply: the agent must show receipts or retract")
    ctx.register_command("capscore", handler=command(engine.capscore, wants_platform=True), args_hint="[card|board]",
                         description="Cap Score: which model caps most, streaks, shareable scorecard; board = Cap Board (this profile)")
    ctx.register_command("nocap", handler=command(engine.nocap), args_hint="[all|battery|doctor|purge|help]",
                         description="No Cap receipts for the last reply, and store admin")

    def setup(subparser: Any) -> None:
        subs = subparser.add_subparsers(dest="nocap_cmd")
        last = subs.add_parser("last", help="Receipts for the most recent checked reply")
        last.add_argument("--session", default="")
        subs.add_parser("all", help="Every receipt line of the most recent checked reply")
        subs.add_parser("score", help="Cap Score leaderboard")
        subs.add_parser("card", help="Write the shareable scorecard image")
        subs.add_parser("board", help="Cap Board: top cappers per agent, model and skill (this profile; board.team_profiles for a team view)")
        subs.add_parser("purge", help="Delete the local receipt store")
        subs.add_parser("path", help="Print where receipts are stored")
        subs.add_parser("doctor", help="Setup checks: reply-transform conflicts, /cap injection, store")
        subs.add_parser("battery", help="Run the bundled synthetic lie/truth battery: precision/recall report (synthetic, "
                                        "not the blind real-run number)")
        subparser.set_defaults(func=cli)

    def cli(args: Any) -> Optional[int]:
        sub = getattr(args, "nocap_cmd", None) or "last"
        if sub == "path":
            print(engine.store.path)
        elif sub == "score":
            print(engine.capscore(""))
        elif sub == "card":
            print(engine.capscore("card"))
        elif sub == "board":
            print(engine.capscore("board", platform="cli"))
        elif sub == "purge":
            print(engine.nocap("purge"))
        elif sub == "doctor":
            text, problems = engine.doctor_report()
            print(text)
            return 1 if problems else 0  # Hermes turns a handler's int into the process exit code
        elif sub == "all":
            print(engine.nocap("all"))
        elif sub == "battery":
            print(engine.battery())
        else:
            print(engine.nocap("", session_id=getattr(args, "session", "") or ""))

    ctx.register_cli_command(name="nocap", help="No Cap receipts, Cap Score and store admin",
                             setup_fn=setup, handler_fn=cli)
