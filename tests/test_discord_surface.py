"""Discord surface: the compact footer, the split guard and the receipt-id store (no discord.py, no Hermes needed).

The tests that drive Hermes's real Discord adapter and real discord.py live in test_discord_hermes.py.
"""
import json
import os
import stat

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.surfaces import discord as dsurf
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT, judge

NBSP = "\u00a0"


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


REPLY = "Fixed the login bug in auth.py. All tests pass ✅, pushed to main, and the deploy is live."
EVS = [T("pytest -q", "3 failed, 41 passed in 0.02s", 1, i=1),
       T("git push origin feat/login", "To ../origin.git\n * [new branch]      feat/login -> feat/login", 0, i=2)]


def receipts():
    return judge(extract_claims(REPLY), EVS)


def R(verdict, text, cite=None, cmd=None, quote="", why="", kind="tests"):
    return {"kind": kind, "text": text, "verdict": verdict, "cite": cite, "tool": "terminal" if cite else None,
            "cmd": cmd, "quote": quote, "why": why, "claim": {"kind": kind}}


# ---- the footer ---------------------------------------------------------------------------------------------
def test_footer_is_discord_markdown_with_each_receipt_in_code_spans():
    out = dsurf.footer(receipts())
    assert out.startswith("**🧾 No Cap**")
    assert "🧢 2 cap" in out.splitlines()[0]
    assert "🧢 `All tests pass ✅` · call 1 `pytest -q` → says `" in out
    assert "🧢 `pushed to main` · call 2 `git push origin feat/login`" in out
    assert "-# " in out.splitlines()[-1] and "/cap" in out.splitlines()[-1]  # subtext hint, only when something is open
    assert "**Receipts**" not in out  # not the generic footer


def test_footer_stays_under_1000_chars_and_collapses_overflow():
    many = [R(NO_CAP, f"claim number {i} " + "x" * 80, cite=i, cmd="pytest -q tests/" + "y" * 60, quote="9 passed")
            for i in range(40)]
    out = dsurf.footer(many)
    assert len(out) <= dsurf.FOOTER_MAX
    shown = [ln for ln in out.splitlines() if ln.startswith("🧾 `")]
    assert 1 <= len(shown) < 40
    assert f"+{40 - len(shown)} more" in out and "/nocap all" in out


def test_every_open_line_is_kept_before_no_cap_lines():
    rs = [R(NO_CAP, f"ok {i}", cite=i, cmd="true") for i in range(10)] + [R(CAP, "pushed to main", cite=11,
                                                                            cmd="git push", quote="feat/x")]
    out = dsurf.footer(rs)
    assert out.splitlines()[1].startswith("🧢 `pushed to main`")


def test_code_spans_cannot_be_broken_out_of():
    r = R(CAP, "done `rm -rf` @everyone <@123> **bold**\nsecond line", cite=1, cmd="echo `x`", quote="a`b")
    line = dsurf.receipt_line(r)
    assert "\n" not in line
    assert line.count("`") % 2 == 0  # every span closes
    for span in line.split("`")[1::2]:
        assert "`" not in span
    assert "@everyone" in line.split("`")[1]  # inside a code span: Discord renders it inert
    assert "rm -rf" in line.split("`")[1]  # the claim's own backticks are markdown: dropped, not shown as ˋ


def test_text_outside_code_spans_is_escaped():
    out = dsurf.footer([], rescore=["🔁 /cap re-score: 🧢 → 🫡 retracted “**x** @here” (tests)"])
    assert "`x @here`" in out  # the agent's words go in a code span (their markdown bold dropped)
    assert "@here" not in out.replace("`x @here`", "")


def test_secrets_in_evidence_are_redacted():
    secret = "DB_" + "PASSWORD=" + "q7" * 6
    out = dsurf.footer([R(CAP, "deployed", cite=1, cmd=f"deploy --env {secret}", quote="failed")])
    assert "q7q7q7q7q7q7" not in out


def test_strict_mode_labels_caps_unverified():
    out = dsurf.footer(receipts(), mode="strict")
    assert "🧢 Unverified `pushed to main`" in out


def test_streak_shows_only_without_caps():
    assert "🔥 4 no cap in a row" in dsurf.footer([R(NO_CAP, "ok", cite=1, cmd="true")], streak=4)
    assert "🔥" not in dsurf.footer(receipts(), streak=4)


def test_all_no_cap_has_no_cap_hint():
    out = dsurf.footer([R(NO_CAP, "All 3 tests pass", cite=1, cmd="pytest", quote="3 passed")])
    assert "/cap" not in out


def test_one_liner_has_no_newline_and_no_plain_space():
    line = dsurf.one_liner(receipts(), notes=["⚠️ This reply contained 1 stamp(s) No Cap didn't issue."])
    assert "\n" not in line and " " not in line
    assert line.replace(NBSP, " ").startswith("**🧾 No Cap** · 🧢 2 cap")
    assert "/nocap" in line and "⚠️" in line


# ---- compose: append-only, quiet, split guard ------------------------------------------------------------------
def test_compose_appends_the_footer():
    out = dsurf.compose("Done.", receipts(), "annotate")
    assert out.startswith("Done.\n\n**🧾 No Cap**")


def test_compose_quiet_and_empty():
    assert dsurf.compose("Done.", receipts(), "quiet") is None
    assert dsurf.compose("Done.", [], "annotate") is None
    assert dsurf.compose("Done.", [], "annotate", notes=["⚠️ x"]) is not None


def test_long_reply_never_gets_a_split_footer_without_hermes():
    body = "\n".join(f"line {i} " + "z" * 50 for i in range(60))  # ~3.5k chars: Discord will split it
    out = dsurf.compose(body, receipts(), "annotate", split=None)
    tail = out[len(body):]
    assert "\n" not in tail.strip("\n")  # the one-liner, which no splitter cuts
    assert NBSP in tail


def test_split_guard_uses_the_splitter_it_is_given():
    def splitter(text):  # cuts at 1990 chars, the way a careless splitter would
        return [text[i:i + 1990] for i in range(0, len(text), 1990)]
    body = "a " * 850
    assert len(body) + len(dsurf.footer(receipts())) > 1990
    out = dsurf.compose(body, receipts(), "annotate", split=splitter)
    assert "\n" not in out[len(body):].strip("\n")  # the full footer would have straddled the cut


def test_unclosed_fence_is_closed_before_the_footer():
    out = dsurf.compose("```python\nprint(1)", receipts(), "annotate")
    assert "print(1)\n```\n\n**🧾 No Cap**" in out


def test_token_mode_uses_the_one_liner_with_the_receipt_id():
    out = dsurf.compose("Done.", receipts(), "annotate", token="0a1b2c3d")
    tail = out.split("\n\n", 1)[1]
    assert "\n" not in tail and f"receipt{NBSP}#0a1b2c3d" in tail
    assert dsurf.TOKEN_RE.findall(out) == ["0a1b2c3d"]


# ---- the surface object: buttons off by default, receipt ids on disk -----------------------------------------
class _Store:
    def __init__(self):
        self.recs = []

    def records(self):
        return list(self.recs)

    def last(self, session_id="", with_receipts=True):
        for r in reversed(self.recs):
            if r.get("session_id") == session_id and r.get("receipts"):
                return r
        return None


class _Engine:
    def __init__(self):
        self.store = _Store()
        self.capped = []

    def cap(self, raw_args="", session_id="", session_key=""):
        self.capped.append((session_id, session_key))
        return "🧢 Cap called on 1 claim(s)."


def _surface(tmp_path, buttons="off", env=None):
    cfg = {"discord_buttons": buttons}
    s = dsurf.DiscordSurface(_Engine(), lambda k, d=None: cfg.get(k, d), lambda: tmp_path, session_env=lambda: env or {})
    return s


class _Bot:
    def __init__(self):
        self.user = type("U", (), {"id": 42})()
        self.listeners = {}

    def add_listener(self, fn, name):
        self.listeners.setdefault(name, []).append(fn)

    def is_closed(self):
        return False


def test_buttons_are_off_by_default(tmp_path):
    s = _surface(tmp_path, buttons=None)
    s.wire(_Bot(), None)
    out = s.compose("Done.", receipts(), "annotate", session_id="s1", turn_id="t1")
    assert dsurf.TOKEN_RE.search(out) is None and "**🧾 No Cap**" in out
    assert not (tmp_path / dsurf.TOKENS_FILE).exists()


def test_buttons_on_but_no_live_bot_falls_back_to_the_footer(tmp_path):
    s = _surface(tmp_path, buttons="on")
    out = s.compose("Done.", receipts(), "annotate", session_id="s1", turn_id="t1")
    assert dsurf.TOKEN_RE.search(out) is None and "🧢 `pushed to main`" in out


def test_wire_registers_three_listeners(tmp_path):
    bot = _Bot()
    _surface(tmp_path).wire(bot, None)
    assert set(bot.listeners) == {"on_message", "on_raw_message_edit", "on_interaction"}


def test_buttons_on_issues_a_private_receipt_id_without_reply_text(tmp_path):
    env = {"HERMES_SESSION_KEY": "agent:main:discord:dm:7", "HERMES_SESSION_USER_ID": "7",
           "HERMES_SESSION_CHAT_ID": "99"}
    s = _surface(tmp_path, buttons="on", env=env)
    s.wire(_Bot(), None)
    out = s.compose("Done.", receipts(), "annotate", session_id="s1", turn_id="t1")
    (tok,) = dsurf.TOKEN_RE.findall(out)
    p = tmp_path / dsurf.TOKENS_FILE
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    saved = json.loads(p.read_text())[tok]
    assert saved["session_id"] == "s1" and saved["turn_id"] == "t1" and saved["user_id"] == "7"
    assert saved["session_key"] == "agent:main:discord:dm:7" and saved["chat_id"] == "99"
    assert "pushed to main" not in p.read_text()  # ids only: the receipts stay in receipts.jsonl


def test_receipt_ids_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(dsurf, "MAX_TOKENS", 5)
    s = _surface(tmp_path, buttons="on", env={"HERMES_SESSION_USER_ID": "7"})
    s.wire(_Bot(), None)
    for i in range(9):
        s.compose("Done.", receipts(), "annotate", session_id=f"s{i}", turn_id="t")
    assert len(json.loads((tmp_path / dsurf.TOKENS_FILE).read_text())) == 5


# ---- engine wiring --------------------------------------------------------------------------------------------
def test_engine_uses_the_discord_footer_only_on_discord(tmp_path):
    from nocap.engine import Engine
    cfg = {}
    eng = Engine(lambda: tmp_path, lambda k, d=None: cfg.get(k, d))
    surf = dsurf.DiscordSurface(eng, eng.setting, eng.data_dir, session_env=lambda: {})
    eng.surfaces["discord"] = surf.compose

    def run(platform, turn):
        for e in EVS:
            eng.on_tool(tool_name="terminal", args={"command": e["cmd"]},
                        result=json.dumps({"output": "3 failed, 41 passed" if "pytest" in e["cmd"] else
                                           " * [new branch]      feat/login -> feat/login",
                                           "exit_code": 1 if "pytest" in e["cmd"] else 0}),
                        session_id="s", turn_id=turn)
        return eng.on_reply(response_text=REPLY, session_id="s", turn_id=turn, platform=platform)

    assert "**🧾 No Cap**" in run("discord", "t1")
    assert "**🧾 No Cap**" not in run("telegram", "t2") and "**Receipts**" in run("telegram", "t3")


def test_plugin_registers_the_discord_handler():
    from test_plugin import load_plugin
    mod = load_plugin()
    calls = []

    class Ctx:
        state = type("S", (), {"data_dir": "/nonexistent-nocap-test"})()

        def get_config(self, k, d=None):
            return d

        def register_hook(self, *a, **k):
            pass

        def register_command(self, *a, **k):
            pass

        def register_cli_command(self, *a, **k):
            pass

        def register_platform_handler(self, platform, factory):
            calls.append((platform, factory))

    mod.register(Ctx())
    assert [p for p, _ in calls] == ["discord"] and callable(calls[0][1])
