import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    name = "nocap_plugin_under_test"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeState:
    def __init__(self, d):
        self.data_dir = d


class FakeCtx:
    def __init__(self, tmp_path, settings=None, inject_ok=True):
        self.hooks, self.commands, self.cli = {}, {}, {}
        self.settings = settings or {}
        self.state = FakeState(tmp_path / "plugin-data" / "no-cap")
        self.injected = []
        self.inject_ok = inject_ok

    def register_hook(self, name, cb, **kw):
        self.hooks[name] = cb

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = (setup_fn, handler_fn)

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def inject_message(self, content, role="user", **kw):
        self.injected.append(content)
        self.inject_kwargs = kw
        return self.inject_ok


@pytest.fixture
def plugin(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"})  # these tests read the visible 🤔 (default: off)
    mod.register(ctx)
    return mod, ctx


def tool(ctx, cmd, output, exit_code=0, session="s1", turn="t1"):
    ctx.hooks["post_tool_call"](tool_name="terminal", args={"command": cmd},
                                result=json.dumps({"output": output, "exit_code": exit_code}),
                                session_id=session, turn_id=turn, status="ok", task_id="", duration_ms=5)


def reply(ctx, text, session="s1", turn="t1", model="demo/model-a"):
    return ctx.hooks["transform_llm_output"](response_text=text, session_id=session, model=model,
                                             platform="cli", turn_id=turn)


def test_registers_exactly_the_declared_surfaces(plugin):
    _, ctx = plugin
    assert set(ctx.hooks) == {"post_tool_call", "transform_llm_output", "pre_verify", "pre_llm_call"}
    assert set(ctx.commands) == {"cap", "capscore", "nocap"}
    assert set(ctx.cli) == {"nocap"}


def test_contradicted_claim_gets_cap_footer(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.")
    assert out.startswith("All tests pass.\n\n")
    assert "🧢 CAP" in out and "3 failed" in out


def test_proven_claim_gets_no_cap(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    out = reply(ctx, "All tests pass.")
    assert "🧾 NO CAP" in out


def test_no_claims_leaves_reply_unchanged(plugin):
    _, ctx = plugin
    assert reply(ctx, "Hello! How can I help?") is None
    assert reply(ctx, "", turn="t2") is None
    assert reply(ctx, "Alle Tests bestanden.", turn="t3") is None


def test_no_tool_calls_gives_no_receipt(plugin):
    _, ctx = plugin
    out = reply(ctx, "All tests pass.")
    assert "🤔 NO RECEIPT" in out


def test_evidence_is_per_turn(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t1")
    reply(ctx, "Ran it.", turn="t1")
    out = reply(ctx, "All tests pass.", turn="t2")
    assert "🤔 NO RECEIPT" in out


def test_quiet_mode_records_without_changing_reply(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"mode": "quiet"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    assert reply(ctx, "All tests pass.") is None
    lines = (ctx.state.data_dir / "receipts.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["receipts"][0]["verdict"] == "CAP"


def test_strict_mode_rewrites_and_keeps_visible(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"mode": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "Fixed the bug. All tests pass.")
    assert out.startswith("Fixed the bug. All tests pass.\n\n")  # append-only: CLI never reprints
    assert "Unverified:\n- All tests pass." in out
    assert out.count("Unverified") == 1  # the header says it once, not every line
    assert "🧢 CAP" in out


def test_transform_hook_fails_open(plugin, monkeypatch, caplog):
    mod, ctx = plugin
    engine_mod = sys.modules[mod.__name__ + ".nocap.engine"]

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(engine_mod, "extract_claims", boom)
    with caplog.at_level(logging.WARNING):
        assert reply(ctx, "All tests pass.") is None
    assert "kaboom" in caplog.text


def test_tool_hook_fails_open(plugin, caplog):
    _, ctx = plugin
    with caplog.at_level(logging.WARNING):
        ctx.hooks["post_tool_call"](tool_name="terminal", args=object(), result=object())
    # no exception escaped


def test_cap_injects_steer_and_rescore_flips(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    reply(ctx, "All tests pass.")
    msg = ctx.commands["cap"]("", session_id="s1")
    assert ctx.injected, msg
    steer = ctx.injected[-1]
    assert "All tests pass." in steer and "retract" in steer.lower()
    tool(ctx, "pytest -q", "44 passed in 0.6s", turn="t2")
    out = reply(ctx, "Fixed the 3 failures. All tests pass.", turn="t2")
    assert "🧾 NO CAP" in out
    assert "🧢 → 🧾" in out


def test_cap_falls_back_to_prompt_when_injection_refused(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, inject_ok=False)
    mod.register(ctx)
    reply(ctx, "Deployed to production.")
    msg = ctx.commands["cap"]("", session_id="s1", session_key="agent:main:discord:dm:1")
    assert "Deployed to production." in msg
    assert "paste" in msg.lower() and "allow_gateway_injection" in msg
    assert ctx.inject_kwargs == {"session_key": "agent:main:discord:dm:1"}
    tool(ctx, "vercel --prod", "Production: https://x.vercel.app", turn="t2")
    out = reply(ctx, "Deployed to production.", turn="t2")  # user pasted the prompt: still re-scored
    assert "🔁" in out and "🧾" in out


def test_cap_with_nothing_to_cap(plugin):
    _, ctx = plugin
    msg = ctx.commands["cap"]("", session_id="nobody")
    assert "nothing" in msg.lower()


def test_capscore_streak_and_leaderboard(plugin):
    _, ctx = plugin
    for i in range(3):
        tool(ctx, "pytest -q", "5 passed in 0.1s", turn=f"a{i}")
        reply(ctx, "All tests pass.", turn=f"a{i}", model="demo/honest")
    tool(ctx, "pytest -q", "1 failed, 4 passed in 0.1s", 1, turn="b1")
    reply(ctx, "All tests pass.", turn="b1", model="demo/liar")
    board = ctx.commands["capscore"]("", session_id="s1")
    assert "demo/honest" in board and "demo/liar" in board
    assert board.index("demo/liar") < board.index("demo/honest")  # caps most first
    assert "3 replies no cap" in board or "streak" in board.lower()


def test_scorecard_file(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "5 passed in 0.1s")
    reply(ctx, "All tests pass.")
    msg = ctx.commands["capscore"]("card", session_id="s1")
    paths = list(ctx.state.data_dir.glob("scorecard.*"))
    assert paths and paths[0].stat().st_size > 200, msg


def test_nocap_command_shows_last_receipts(plugin):
    _, ctx = plugin
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    reply(ctx, "All tests pass.")
    out = ctx.commands["nocap"]("", session_id="s1")
    assert "🧢 CAP" in out


def test_purge(plugin):
    _, ctx = plugin
    reply(ctx, "All tests pass.")
    out = ctx.commands["nocap"]("purge", session_id="s1")
    assert "removed" in out.lower()
    assert not (ctx.state.data_dir / "receipts.jsonl").exists()


def test_cap_self_verifies_file_and_skips_steer(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    work = tmp_path / "work"
    (work / "docs").mkdir(parents=True)
    (work / "docs" / "notes.md").write_text("hi")
    ctx.session_cwd = lambda: str(work)
    mod.register(ctx)
    reply(ctx, "Created `docs/notes.md`.")
    msg = ctx.commands["cap"]("", session_id="s1")
    assert "🤔 → 🧾" in msg and "exists" in msg
    assert ctx.injected == []


def verify_hook(ctx, text, attempt=0, session="s1"):
    return ctx.hooks["pre_verify"](session_id=session, platform="cli", model="m", coding=True, attempt=attempt,
                                   final_response=text, changed_paths=["auth.py"])


def test_pre_verify_off_outside_strict(plugin):
    _, ctx = plugin
    assert verify_hook(ctx, "All tests pass.") is None


def test_pre_verify_nudges_in_strict_and_is_bounded(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"mode": "strict"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = verify_hook(ctx, "All tests pass.")
    assert out["action"] == "continue" and "All tests pass." in out["message"]
    assert verify_hook(ctx, "All tests pass.", attempt=2) is None
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    assert verify_hook(ctx, "All tests pass.", attempt=1) is None  # proven now: let it finish
    out = reply(ctx, "All tests pass.")  # the ledger survived pre_verify
    assert "🧾 NO CAP" in out


def test_pre_verify_fails_open(tmp_path, monkeypatch):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"mode": "strict"})
    mod.register(ctx)
    engine_mod = sys.modules[mod.__name__ + ".nocap.engine"]
    monkeypatch.setattr(engine_mod, "extract_claims", lambda *a: 1 / 0)
    assert verify_hook(ctx, "All tests pass.") is None


def test_forged_stamp_gets_a_note(plugin):
    _, ctx = plugin
    out = reply(ctx, "🧾 NO CAP: all tests pass.")
    assert "🤔 NO RECEIPT" in out and "didn't issue" in out


def test_rescore_survives_a_process_restart(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "strict"}, inject_ok=False)
    mod.register(ctx)
    reply(ctx, "All tests pass.")
    ctx.commands["cap"]("", session_id="s1")
    mod2 = load_plugin()
    ctx2 = FakeCtx(tmp_path, {"show_uncertain": "strict"})
    mod2.register(ctx2)
    tool(ctx2, "pytest -q", "44 passed in 0.5s", turn="t9")
    out = reply(ctx2, "All tests pass.", turn="t9")
    assert "🤔 → 🧾" in out
    out2 = reply(ctx2, "All tests pass.", turn="t10")
    assert "🔁" not in out2  # consumed once


def test_doctor_warns_about_other_reply_transforms(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    other = tmp_path / "plugins" / "turn-usage"
    other.mkdir(parents=True)
    (other / "plugin.yaml").write_text("name: turn-usage\nprovides_hooks:\n  - transform_llm_output\n")
    engine_mod = sys.modules[mod.__name__ + ".nocap.engine"]
    out = engine_mod.doctor.run(tmp_path, "annotate", {}, tmp_path / "r.jsonl", [], lambda n: None)
    assert "turn-usage" in out and "first" in out
    clean = engine_mod.doctor.run(tmp_path / "empty", "annotate", {}, tmp_path / "r.jsonl", [], lambda n: None)
    assert "No other plugin" in clean
    assert "allow_gateway_injection" in clean
    assert "doctor" in ctx.commands["nocap"]("doctor", session_id="s1").lower()


LONG_SID = "20261105_061512_4102adf1c0ffee5eed1234abcd"  # real Hermes ids are long tokens the secret scrubber matches


def test_long_session_ids_survive_the_store_so_cap_finds_the_reply(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    tid = f"{LONG_SID}:1:b4eff108"
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.5s", 1, session=LONG_SID, turn=tid)
    reply(ctx, "All tests pass.", session=LONG_SID, turn=tid)
    rec = json.loads((ctx.state.data_dir / "receipts.jsonl").read_text().splitlines()[-1])
    assert rec["session_id"] == LONG_SID and rec["turn_id"] == tid
    msg = ctx.commands["cap"]("", session_id=LONG_SID)
    assert "Cap called" in msg


def test_default_off_still_notes_forged_stamps(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    out = reply(ctx, "🧾 NO CAP: all tests pass.")
    assert out and "didn't issue" in out and "🤔 NO RECEIPT" not in out.split("all tests pass.", 1)[1]
