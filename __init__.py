"""No Cap: receipts for agent claims.

Hooks and three slash commands, public plugin surfaces only:
  post_tool_call        → record an evidence ledger for the turn (facts only, raw output never stored)
  transform_llm_output  → check the final reply's claims against that ledger, append the receipts
  pre_llm_call          → Cap Coach: inject the coach rules the user approved (/cap coach), labelled, in scope
  /cap /capscore /nocap → call cap on the last reply, honesty leaderboard, receipts and store admin
  dashboard/            → the Cap Board tab: this profile's store ranked live (team view opt-in), read-only
  hermes nocap ...      → the same from a terminal

Fail open by design: if anything in here raises, the reply goes out unchanged and the error is logged.
A missed flag costs less than a broken reply.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Optional

from .nocap import compare_card, export, ladder, verdict_card
from .nocap.engine import Engine, is_local
from .nocap.surfaces.discord import DiscordSurface

logger = logging.getLogger("hermes_plugins.no_cap")

__version__ = "0.2.0"


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
                if wants_key:  # /cap: the platform too, so coach changes stay local-only (judge review S12)
                    return fn(raw_args or "", session_id=session_id or "", session_key=session_key or "",
                              platform=str(platform or ""))
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

    def on_turn_start(**kwargs: Any) -> Optional[dict]:
        try:
            return engine.on_turn_start(**kwargs)
        except Exception as exc:  # fail open: the turn runs without coach rules
            logger.warning("no-cap: pre_llm_call (coach) failed open: %s", exc, exc_info=True)
            return None

    ctx.register_hook("pre_llm_call", on_turn_start)
    ctx.register_command("cap", handler=command(engine.cap, wants_key=True), args_hint="[coach ...]",
                         description="Call cap on the last reply (the agent must show receipts or retract); "
                                     "/cap coach: what this agent caps on and approved fixes")
    ctx.register_command("capscore", handler=command(engine.capscore, wants_platform=True), args_hint="[card|board]",
                         description="Cap Score: which model caps most, streaks, shareable scorecard; board = Cap Board (this profile)")
    ctx.register_command("nocap", handler=command(engine.nocap), args_hint="[all|battery|doctor|purge|help]",
                         description="No Cap receipts for the last reply, and store admin")

    # Showpieces (verdict card, A/B card, Lie Ladder): /capscore and /nocap are registered again with wrappers that
    # add the new subcommands and fall through to the engine. Hermes keeps the last registration of a name.
    data = lambda: Path(engine.data_dir())

    def capscore(raw_args: str = "", session_id: str = "", platform: str = "") -> str:
        if (raw_args or "").strip().lower().split()[:1] == ["compare"]:
            return compare_card.command(engine.store.records(), data(), raw_args)
        return engine.capscore(raw_args, session_id=session_id, platform=platform)

    def nocap(raw_args: str = "", session_id: str = "", platform: str = "") -> str:
        words = (raw_args or "").strip().lower().split()
        local = is_local(platform)
        if words[:1] == ["verdict"]:  # a chat never falls back to another session's verdict (judge review S2)
            return verdict_card.command(engine.store.records(), data(), session_id, local=local)
        if words[:1] == ["demo"]:
            if words[1:2] != ["ladder"]:
                return "Usage: /nocap demo ladder  (or `hermes nocap demo --ladder` in a terminal)"
            return ladder.start(platform)
        out = engine.nocap(raw_args, session_id=session_id, platform=platform)
        if words[:1] == ["purge"] and local:  # the verdict and compare cards quote claims too: they go with the store
            verdict_card.remove(data())
            compare_card.remove(data())
        elif words[:1] in (["help"], ["?"]):
            out += (" · /nocap verdict → courtroom verdict card for this session · /capscore compare A B → honesty "
                    "A/B card · /nocap demo ladder → the Lie Ladder demo (local)")
        return out

    ctx.register_command("capscore", handler=command(capscore, wants_platform=True),
                         args_hint="[card|board|compare A B]",
                         description="Cap Score: which model caps most, streaks, shareable scorecard; board = Cap Board "
                                     "(this profile); compare A B = honesty A/B card")
    ctx.register_command("nocap", handler=command(nocap, wants_platform=True),
                         args_hint="[all|verdict|battery|doctor|purge|demo ladder|help]",
                         description="No Cap receipts for the last reply, the session verdict card, and store admin")

    def setup(subparser: Any) -> None:
        subs = subparser.add_subparsers(dest="nocap_cmd")
        last = subs.add_parser("last", help="Receipts for the most recent checked reply")
        last.add_argument("--session", default="")
        subs.add_parser("all", help="Every receipt line of the most recent checked reply")
        subs.add_parser("score", help="Cap Score leaderboard")
        subs.add_parser("card", help="Write the shareable scorecard image")
        subs.add_parser("board", help="Cap Board: top cappers per agent, model and skill (this profile; board.team_profiles for a team view)")
        v = subs.add_parser("verdict", help="Courtroom verdict card (SVG + PNG) for a session's receipts")
        v.add_argument("--session", default="", help="session id (default: the latest session with receipts)")
        sc = subs.add_parser("scorecard", help="Shareable scorecard; --compare A B for the honesty A/B card")
        sc.add_argument("--compare", nargs=2, metavar=("MODEL_A", "MODEL_B"))
        ex = subs.add_parser("export", help="Export receipts (redacted) as JSON or CSV")
        fmt = ex.add_mutually_exclusive_group(required=True)
        fmt.add_argument("--json", action="store_true")
        fmt.add_argument("--csv", action="store_true")
        ex.add_argument("--out", default="", help="write to this file (0600) instead of stdout")
        me = subs.add_parser("metrics", help="Write Prometheus text-format metrics to a file (no port, no listener)")
        me.add_argument("--file", required=True)
        de = subs.add_parser("demo", help="Demo theater; --ladder runs the Lie Ladder in a throwaway home")
        de.add_argument("--ladder", action="store_true", required=True)
        de.add_argument("--out", default="", help="output folder (default: a new one under /tmp)")
        subs.add_parser("purge", help="Delete the local receipt store")
        subs.add_parser("path", help="Print where receipts are stored")
        subs.add_parser("doctor", help="Setup checks: reply-transform conflicts, /cap injection, store")
        coach = subs.add_parser("coach", help="Cap Coach: status | scan | show ID | approve ID [rule|skill|memory] "
                                              "[--apply] | revert ID | dismiss ID | rules")
        coach.add_argument("coach_args", nargs=argparse.REMAINDER)
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
        elif sub == "verdict":
            print(verdict_card.command(engine.store.records(), data(), getattr(args, "session", "") or ""))
        elif sub == "scorecard":
            pair = getattr(args, "compare", None)
            if pair:
                print(compare_card.command(engine.store.records(), data(), " ".join(_quote(x) for x in pair)))
            else:
                print(engine.capscore("card"))
        elif sub == "export":
            text = export.to_json(engine.store.records()) if args.json else export.to_csv(engine.store.records())
            if args.out:
                try:
                    print(f"wrote {export.write_private(Path(args.out), text)}")
                except OSError as exc:
                    print(f"no-cap: can't write {args.out}: {exc}")
                    return 1
            else:
                print(text, end="")
        elif sub == "metrics":
            try:
                path = export.write_private(Path(args.file), export.metrics(engine.store.records()))
            except OSError as exc:
                print(f"no-cap: can't write {args.file}: {exc}")
                return 1
            print(f"wrote {path} (Prometheus text format; file only, no listener)")
        elif sub == "demo":
            return ladder.run(getattr(args, "out", "") or None)
        elif sub == "all":
            print(engine.nocap("all"))
        elif sub == "coach":
            print(engine.coach.command(list(getattr(args, "coach_args", None) or [])))
        elif sub == "battery":
            print(engine.battery())
        else:
            print(engine.nocap("", session_id=getattr(args, "session", "") or ""))

    def _quote(x: str) -> str:
        import shlex
        return shlex.quote(x)

    ctx.register_cli_command(name="nocap", help="No Cap receipts, Cap Score and store admin",
                             setup_fn=setup, handler_fn=cli)
