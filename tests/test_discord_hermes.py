"""No Cap on Hermes's real Discord adapter, with real discord.py objects and a fake Discord connection.

Runs only where Hermes and discord.py import (skipped in CI). Locally:

    NOCAP_HERMES_SRC=<hermes-agent checkout> HERMES_HOME=$(mktemp -d) \
      <python with discord.py> -m pytest -c tests/pytest.ini tests/test_discord_hermes.py

HERMES_HOME must be a throwaway directory: the adapter's delivery ledger and the plugin store write under it.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = os.environ.get("NOCAP_HERMES_SRC", "")
if not SRC:
    pytest.skip("NOCAP_HERMES_SRC not set: Hermes integration tests skipped", allow_module_level=True)
if not os.environ.get("HERMES_HOME", "").startswith(tempfile.gettempdir().rstrip("/")) and \
        not os.environ.get("HERMES_HOME", "").startswith("/tmp"):
    pytest.skip("HERMES_HOME must point at a throwaway temp dir for these tests", allow_module_level=True)
sys.path.insert(0, SRC)
discord = pytest.importorskip("discord")
from gateway.config import PlatformConfig  # noqa: E402
from plugins.platforms.discord.adapter import DiscordAdapter  # noqa: E402

from nocap.surfaces import discord as dsurf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPLY = "Fixed the login bug. All tests pass ✅, pushed to main, and the deploy is live."
TOOLS = [("pytest -q", "3 failed, 41 passed in 0.02s", 1),
         ("git push origin feat/login", "To ../origin.git\n * [new branch]      feat/login -> feat/login", 0)]


# ---- fakes for the Discord connection (everything else is real) ---------------------------------------------------
class FakeChannel:
    def __init__(self, cid=555):
        self.id, self.sent = cid, []

    async def send(self, content=None, reference=None, **kw):
        self.sent.append(content)
        return SimpleNamespace(id=9000 + len(self.sent), content=content)


class FakeBot:
    def __init__(self):
        self.user = SimpleNamespace(id=4242)
        self.listeners, self.edits = {}, []

    def add_listener(self, fn, name):
        self.listeners.setdefault(name, []).append(fn)

    def is_closed(self):
        return False

    def get_partial_messageable(self, cid):
        bot = self

        class _Msg:
            def __init__(self, mid):
                self.id = mid

            async def edit(self, **kw):
                bot.edits.append((cid, self.id, kw))

        return SimpleNamespace(get_partial_message=lambda mid: _Msg(mid))

    async def fire(self, name, *args):
        for fn in self.listeners.get(name, []):
            await fn(*args)


class FakeInteraction:
    def __init__(self, custom_id, user_id):
        self.data = {"custom_id": custom_id, "component_type": 2}
        self.user = SimpleNamespace(id=int(user_id))
        self.answers, self.view_edits, self._done = [], [], False
        outer = self

        class _Resp:
            def is_done(self):
                return outer._done

            async def send_message(self, text, **kw):
                outer._done = True
                outer.answers.append((text, kw))

            async def defer(self, **kw):
                outer._done = True

        class _Follow:
            async def send(self, text, **kw):
                outer.answers.append((text, kw))

        class _Message:
            async def edit(self, **kw):
                outer.view_edits.append(kw)

        self.response, self.followup, self.message = _Resp(), _Follow(), _Message()


def make_adapter(channel):
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="***"))

    async def _fetch(_cid):
        return channel

    adapter._client = SimpleNamespace(get_channel=lambda _cid: channel, fetch_channel=_fetch)
    return adapter


def sent_text(channel):
    return [dsurf._INDICATOR.sub("", c) for c in channel.sent]


# ---- 1. the footer through the real send path ----------------------------------------------------------------------
def _receipts():
    from nocap.claims import extract_claims
    from nocap.evidence import extract
    from nocap.verdict import judge
    evs = [extract("terminal", {"command": c}, json.dumps({"output": o, "exit_code": x}), index=i + 1)
           for i, (c, o, x) in enumerate(TOOLS)]
    return judge(extract_claims(REPLY), evs)


def test_short_reply_gets_the_full_footer_in_one_message():
    ch = FakeChannel()
    out = dsurf.compose(REPLY, _receipts(), "annotate")
    assert asyncio.run(make_adapter(ch).send("555", out)).success
    assert len(ch.sent) == 1 and "🧢 `pushed to main` · call 2" in ch.sent[0]


@pytest.mark.parametrize("shape", ["lines", "prose", "code"])
def test_the_footer_is_never_split_across_messages(shape):
    """Sweep reply lengths across several 2000-char boundaries: the footer always arrives whole in one message."""
    receipts = _receipts()
    used_full = used_small = 0
    for n in range(1200, 9000, 41):
        if shape == "lines":
            body = "\n".join(f"step {i}: " + "w" * 37 for i in range(n // 46))[:n]
        elif shape == "prose":
            body = ("word " * (n // 5))[:n]
        else:
            body = "Here:\n```python\n" + "\n".join(f"x{i} = {i}" for i in range(n // 9)) + "\n```\nDone."
        out = dsurf.compose(body, receipts, "annotate")
        tail = out[len(body):].lstrip("\n`").lstrip("\n")
        ch = FakeChannel()
        assert asyncio.run(make_adapter(ch).send("555", out)).success
        assert any(tail in c for c in sent_text(ch)), (shape, n, [len(c) for c in ch.sent])
        if "\n" in tail:
            used_full += 1
        else:
            used_small += 1
    assert used_full and used_small  # both shapes of footer were exercised


def test_tables_are_converted_by_hermes_before_the_split_check():
    table = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | {'v' * 30} |" for i in range(60))
    out = dsurf.compose(table, _receipts(), "annotate")
    tail = out[len(table):].strip("\n")
    ch = FakeChannel()
    asyncio.run(make_adapter(ch).send("555", out))
    assert any(tail in c for c in sent_text(ch))


# ---- 2. the real plugin, registered through Hermes's real PluginContext ----------------------------------------
@pytest.fixture
def plugin(monkeypatch, tmp_path):
    home = Path(os.environ["HERMES_HOME"])

    def configure(allow_gateway_injection=None, **settings):
        entry = {"settings": settings}
        if allow_gateway_injection is not None:
            entry["allow_gateway_injection"] = allow_gateway_injection
        (home / "config.yaml").write_text(json.dumps({"plugins": {"enabled": ["no-cap"],
                                                                    "entries": {"no-cap": entry}}}))
    configure(discord_buttons="on")
    import hermes_cli.plugins as hp
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
    mgr = PluginManager()
    ctx = PluginContext(manifest=PluginManifest(name="no-cap", version="0.1.0", description="t"), manager=mgr)
    monkeypatch.setattr(hp, "get_plugin_manager", lambda: mgr)
    from test_plugin import load_plugin
    load_plugin().register(ctx)
    return SimpleNamespace(mgr=mgr, ctx=ctx, configure=configure, home=home)


def _turn(plugin, turn_id, user_id="7"):
    from gateway.session_context import clear_session_vars, set_session_vars
    tokens = set_session_vars(platform="discord", chat_id="555", chat_type="dm", user_id=user_id,
                              session_key="agent:main:discord:dm:555", session_id="s1")
    try:
        for cmd, out, code in TOOLS:  # Hermes's real hook dispatcher (worker thread + copy_context, timeouts)
            plugin.mgr.invoke_hook("post_tool_call", tool_name="terminal", args={"command": cmd},
                                   result=json.dumps({"output": out, "exit_code": code}), session_id="s1",
                                   turn_id=turn_id)
        res = plugin.mgr.invoke_hook("transform_llm_output", response_text=REPLY, session_id="s1", turn_id=turn_id,
                                     model="m", platform="discord")
        return next(r for r in res if isinstance(r, str))
    finally:
        clear_session_vars(tokens)


def test_real_adapter_wires_the_plugin_listeners(plugin):
    bot = FakeBot()
    make_adapter(FakeChannel())._wire_plugin_handlers(bot)
    assert set(bot.listeners) >= {"on_message", "on_raw_message_edit", "on_interaction"}


def test_reply_gets_an_embed_and_buttons_end_to_end(plugin):
    async def run():
        bot, ch = FakeBot(), FakeChannel()
        adapter = make_adapter(ch)
        adapter._wire_plugin_handlers(bot)
        out = _turn(plugin, "t1")
        assert dsurf.TOKEN_RE.search(out), out
        assert (await adapter.send("555", out)).success
        for i, content in enumerate(ch.sent):  # Discord echoes the bot's own messages back as MESSAGE_CREATE
            await bot.fire("on_message", SimpleNamespace(id=9001 + i, content=content, channel=SimpleNamespace(id=555),
                                                         author=SimpleNamespace(id=4242)))
        return bot, out

    bot, out = asyncio.run(run())
    assert len(bot.edits) == 1
    cid, mid, kw = bot.edits[0]
    embed, view = kw["embed"], kw["view"]
    assert isinstance(embed, discord.Embed) and isinstance(view, discord.ui.View)
    assert embed.colour.value == dsurf.COLOUR["CAP"]
    assert "pushed to main" in embed.description and embed.footer.text.endswith(dsurf.TOKEN_RE.search(out).group(0)
                                                                                 .replace("\u00a0", " "))
    ids = sorted(c.custom_id for c in view.children)
    tok = dsurf.TOKEN_RE.search(out).group(1)
    assert ids == [f"nocap:cap:{tok}", f"nocap:show:{tok}"]
    assert [c.disabled for c in view.children if c.custom_id.startswith("nocap:cap")] == [False]


def test_other_peoples_messages_and_echoed_ids_are_ignored(plugin):
    async def run():
        bot = FakeBot()
        make_adapter(FakeChannel())._wire_plugin_handlers(bot)
        out = _turn(plugin, "t1")
        await bot.fire("on_message", SimpleNamespace(id=1, content=out, channel=SimpleNamespace(id=555),
                                                     author=SimpleNamespace(id=7)))  # a user quoting the reply
        await bot.fire("on_message", SimpleNamespace(id=2, content=out, channel=SimpleNamespace(id=999),
                                                     author=SimpleNamespace(id=4242)))  # another channel
        return bot

    assert asyncio.run(run()).edits == []


def test_streamed_final_edit_attaches_too(plugin):
    async def run():
        bot = FakeBot()
        make_adapter(FakeChannel())._wire_plugin_handlers(bot)
        out = _turn(plugin, "t1")
        await bot.fire("on_raw_message_edit", SimpleNamespace(channel_id=555, message_id=77,
                                                              data={"content": out, "author": {"id": "4242"}}))
        return bot

    assert [e[1] for e in asyncio.run(run()).edits] == [77]


def _click(plugin, action, user_id="7", setup=None):
    async def run():
        bot = FakeBot()
        make_adapter(FakeChannel())._wire_plugin_handlers(bot)
        out = _turn(plugin, "t1")
        tok = dsurf.TOKEN_RE.search(out).group(1)
        it = FakeInteraction(f"nocap:{action}:{tok}", user_id)
        await bot.fire("on_interaction", it)
        return it

    return asyncio.run(run())


def test_show_receipts_is_private_and_cites_the_calls(plugin):
    it = _click(plugin, "show")
    (text, kw), = it.answers
    assert kw["ephemeral"] is True and isinstance(kw["allowed_mentions"], discord.AllowedMentions)
    assert "pushed to main" in text and "git push origin feat/login" in text and "Cited calls" in text


def test_someone_else_cannot_click(plugin):
    it = _click(plugin, "show", user_id="8")
    assert "Only the person" in it.answers[0][0]
    it = _click(plugin, "cap", user_id="8")
    assert "Only the person" in it.answers[0][0]


def test_call_cap_without_injection_rights_answers_with_the_prompt(plugin):
    plugin.configure(discord_buttons="on")  # allow_gateway_injection not set
    it = _click(plugin, "cap")
    text = it.answers[-1][0]
    assert "allow_gateway_injection" in text and "```text\n[No Cap]" in text and "pushed to main" in text
    assert it.view_edits == []


def test_call_cap_injects_into_the_same_session(plugin):
    plugin.configure(discord_buttons="on", allow_gateway_injection=True)
    got = []
    owner = object()
    plugin.mgr.set_gateway_message_injector(owner, lambda **kw: got.append(kw) or True)
    it = _click(plugin, "cap")
    assert "Cap called on" in it.answers[-1][0]
    assert got and got[0]["session_key"] == "agent:main:discord:dm:555" and "[No Cap]" in got[0]["content"]
    (edit,) = it.view_edits
    cap_btn = [c for c in edit["view"].children if c.custom_id.startswith("nocap:cap")][0]
    assert cap_btn.disabled and cap_btn.label == "Cap called"


def test_buttons_off_means_no_listener_activity(plugin):
    plugin.configure()  # discord_buttons unset
    out = _turn(plugin, "t9")
    assert dsurf.TOKEN_RE.search(out) is None and "🧢 `pushed to main`" in out
