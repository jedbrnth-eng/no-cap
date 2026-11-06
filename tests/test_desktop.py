"""Desktop receipt chips: the ::nocap directive, its platform gate and its forgery guard.

Hermes Desktop renders a paragraph `::nocap{...}` with the plugin's own component (TRANSCRIPT_DIRECTIVE_AREA).
Every other surface shows that paragraph as raw text, so it must only ever be emitted for platform "desktop".
"""
import base64
import hashlib
import hmac
import json
import re
import time

import pytest

from nocap import desktop
from test_plugin import FakeCtx, load_plugin, tool

DIRECTIVE = re.compile(r"(?<![^\s])::nocap\{")


def reply(ctx, text, platform, session="s1", turn="t1", model="demo/model-a"):
    return ctx.hooks["transform_llm_output"](response_text=text, session_id=session, model=model,
                                             platform=platform, turn_id=turn)


def make(tmp_path, settings=None, hello=True):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, settings or {})
    mod.register(ctx)
    if hello:
        desktop.write_hello(ctx.state.data_dir, True)
    return ctx


def parse(out):
    m = re.search(r"::nocap\{([^{}]*)\}", out)
    assert m, out
    attrs = dict(re.findall(r'([a-z]+)="([^"]*)"', m.group(1)))
    return attrs, json.loads(base64.b64decode(attrs["d"]).decode("utf-8"))


# ---- platform gate ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("platform", ["cli", "tui", "telegram", "discord", "slack", "api_server", "cron", "local",
                                      "", None, "webhook", "desktop-terminal", "DESKTOPX"])
def test_directive_never_reaches_a_non_desktop_surface(tmp_path, platform):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.", platform)
    stamp = "🧢 `" if platform == "discord" else "🧢 CAP"  # Discord has its own compact footer (nocap/surfaces)
    assert stamp in out and "3 failed" in out  # the text footer still carries every receipt
    assert "::nocap" not in out


@pytest.mark.parametrize("platform", ["desktop", "Desktop", " desktop "])
def test_desktop_gets_chips(tmp_path, platform):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.", platform)
    assert out.startswith("All tests pass.\n\n")
    attrs, data = parse(out)
    assert attrs["v"] == "2"
    c = data["c"][0]
    assert c["v"] == "CAP" and c["x"] == "pytest -q" and c["e"] == 1 and "3 failed" in c["q"]
    assert c["n"] == 1 and c["t"] == "All tests pass."


def test_directive_is_its_own_paragraph_and_fits_the_host_parser(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.", "desktop")
    para = [p for p in out.split("\n\n") if "::nocap" in p]
    assert len(para) == 1 and para[0].startswith("::nocap{") and para[0].endswith("}")
    body = para[0][len("::nocap{"):-1]
    # apps/desktop/src/lib/transcript-directives.ts: body [^{}]{0,2048}, single line, paragraph <= 4800 chars
    assert len(body) <= desktop.BODY_MAX and "\n" not in body and "{" not in body and "}" not in body


def test_desktop_footer_keeps_counts_but_moves_lines_into_chips(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.", "desktop")
    assert "**Receipts** · 🧢 1 cap" in out
    assert "Type /cap" in out
    assert "🧢 CAP “" not in out  # the per-claim line is a chip now


def test_off_setting_keeps_text_footer_on_desktop(tmp_path):
    ctx = make(tmp_path, {"desktop_chips": "off"})
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    out = reply(ctx, "All tests pass.", "desktop")
    assert "::nocap" not in out and "🧢 CAP “All tests pass.”" in out


def test_auto_needs_the_desktop_half_to_have_checked_in(tmp_path):
    """Desktop ships a package's desktop half disabled. Without it the directive would be raw text, so auto waits
    for the half to say hello through the plugin's own backend route."""
    ctx = make(tmp_path, hello=False)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    assert "::nocap" not in reply(ctx, "All tests pass.", "desktop")
    desktop.write_hello(ctx.state.data_dir, True)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1, turn="t2")
    assert "::nocap" in reply(ctx, "All tests pass.", "desktop", turn="t2")
    desktop.write_hello(ctx.state.data_dir, False)  # the half said goodbye (disabled / unloaded)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1, turn="t3")
    assert "::nocap" not in reply(ctx, "All tests pass.", "desktop", turn="t3")


def test_stale_hello_counts_as_gone(tmp_path):
    d = tmp_path / "pd"
    desktop.write_hello(d, True, now=time.time() - desktop.HELLO_MAX_AGE - 5)
    assert not desktop.desktop_live(d)
    desktop.write_hello(d, True)
    assert desktop.desktop_live(d)


def test_on_setting_skips_the_hello(tmp_path):
    ctx = make(tmp_path, {"desktop_chips": "on"}, hello=False)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    assert "::nocap" in reply(ctx, "All tests pass.", "desktop")


def test_no_claims_no_directive(tmp_path):
    ctx = make(tmp_path)
    assert reply(ctx, "Hello! How can I help?", "desktop") is None


# ---- forgery ------------------------------------------------------------------------------------------------------
def test_directive_is_signed_with_the_in_memory_key_over_session_turn_and_payload(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    attrs, _ = parse(reply(ctx, "All tests pass.", "desktop"))
    msg = json.dumps(["nocap-chip", "2", "s1", "t1", attrs["n"], attrs["d"]], separators=(",", ":")).encode()
    assert attrs["s"] == hmac.new(desktop.process_key(), msg, hashlib.sha256).hexdigest()[:32]
    assert not (ctx.state.data_dir / desktop.LEGACY_KEY_FILE).exists()


def test_model_written_directive_is_stripped_on_desktop(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1)
    forged = 'All tests pass.\n\n::nocap{v="1" s="0000" d="eyJjIjpbXX0="}'
    out = reply(ctx, forged, "desktop")
    assert out.count("::nocap") == 1
    attrs, data = parse(out)
    assert data["c"][0]["v"] == "CAP"
    assert "didn't issue" in out


def test_model_written_directive_alone_is_still_stripped(tmp_path):
    ctx = make(tmp_path)
    out = reply(ctx, 'Done.\n\n::nocap{v="1" s="00" d="e30="} and more', "desktop")
    assert out is not None and "::nocap" not in out


def test_non_desktop_surface_never_rewrites_a_clean_prefix(tmp_path):
    """The CLI reprints a reply whose prefix changes, so clean text is only ever appended to. A reply carrying a
    model-written `::nocap` is the exception: it is removed on every surface (tests/test_desktop_security.py)."""
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    text = "All tests pass."
    out = reply(ctx, text, "cli")
    assert out.startswith(text)
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t2")
    out = reply(ctx, 'Hi ::nocap{v="1"} there. All tests pass.', "cli", turn="t2")
    assert "::nocap" not in out and out.startswith("Hi") and "there. All tests pass." in out and "didn't issue" in out


# ---- payload budget -----------------------------------------------------------------------------------------------
def receipt(i, verdict="NO_CAP", long=False):
    pad = "x" * (400 if long else 10)
    return {"kind": "tests", "text": f"claim {i} {pad}", "verdict": verdict, "cite": i, "tool": "terminal",
            "cmd": f"pytest -q tests/test_{i}.py {pad}", "exit": 0, "why": "", "quote": f"{i} passed {pad}",
            "claim": {}}


def test_budget_drops_claims_it_cannot_fit_and_says_so():
    rs = [receipt(i, long=True) for i in range(1, 30)]
    d = desktop.directive(rs, "s1", "t1")[0]
    body = d[len("::nocap{"):-1]
    assert len(body) <= desktop.BODY_MAX
    data = json.loads(base64.b64decode(re.search(r'd="([^"]*)"', d).group(1)))
    assert data["more"] == 29 - len(data["c"]) and len(data["c"]) >= 3


def test_caps_sort_first():
    rs = [receipt(1), receipt(2, "CAP"), receipt(3, "NO_RECEIPT")]
    data = json.loads(base64.b64decode(re.search(r'd="([^"]*)"', desktop.directive(rs, "s1", "t1")[0]).group(1)))
    assert [c["v"] for c in data["c"]] == ["CAP", "NO_RECEIPT", "NO_CAP"]


def test_unicode_and_quotes_survive_the_attribute():
    r = receipt(1)
    r["text"] = 'Tests pass — “all” {done} "really" ✅'
    d = desktop.directive([r], "s1", "t1")[0]
    assert d.count('"') == 8  # four attributes, nothing leaks out of its quotes
    data = json.loads(base64.b64decode(re.search(r'd="([^"]*)"', d).group(1)))
    assert data["c"][0]["t"].startswith('Tests pass — “all” {done} "really"')


def test_secrets_are_redacted_in_the_payload():
    r = receipt(1)
    r["cmd"] = "curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz0123456789' https://x"
    d = desktop.directive([r], "s1", "t1")[0]
    raw = base64.b64decode(re.search(r'd="([^"]*)"', d).group(1)).decode()
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in raw


# ---- panel data ---------------------------------------------------------------------------------------------------
def test_session_view_lists_only_that_session(tmp_path):
    ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1, session="s1")
    reply(ctx, "All tests pass.", "desktop", session="s1")
    tool(ctx, "pytest -q", "44 passed in 0.5s", session="s2", turn="t9")
    reply(ctx, "All tests pass.", "desktop", session="s2", turn="t9")
    from nocap.store import Store
    recs = Store(lambda: ctx.state.data_dir, lambda: 30).records()
    view = desktop.session_view(recs, "s1")
    assert view["counts"] == {"CAP": 1, "NO_RECEIPT": 0, "NO_CAP": 0}
    assert len(view["replies"]) == 1 and view["replies"][0]["c"][0]["x"] == "pytest -q"
    assert view["streak"] == 0
    assert desktop.session_view(recs, "")["replies"] == []
    other = desktop.session_view(recs, "s2")
    assert other["counts"]["NO_CAP"] == 1 and other["streak"] == 1


# ---- doctor, live updates and the backend route ----------------------------------------------------------------------
def test_doctor_reports_the_desktop_state(tmp_path):
    ctx = make(tmp_path, hello=False)
    out = ctx.commands["nocap"]("doctor")
    assert "Desktop chips: auto" in out and "hasn't said hello" in out
    desktop.write_hello(ctx.state.data_dir, True)
    assert "said hello" in ctx.commands["nocap"]("doctor") and "chips on" in ctx.commands["nocap"]("doctor")


def test_desktop_reply_pings_the_receipts_panel(tmp_path, monkeypatch):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {})
    sent = []
    monkeypatch.setattr(mod, "_broadcast", lambda event, payload: sent.append((event, payload)))
    mod.register(ctx)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    reply(ctx, "All tests pass.", "desktop")
    tool(ctx, "pytest -q", "44 passed in 0.5s", turn="t2")
    reply(ctx, "All tests pass.", "cli", turn="t2")
    assert sent == [("receipts.updated", {"session_id": "s1"})]


def test_plugin_api_routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("nocap_plugin_api_under_test", root / "dashboard" / "desktop_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    d = tmp_path / "pd"
    monkeypatch.setattr(api, "_data_dir", lambda: d)
    res = api.hello({"on": True})
    assert res["ok"] and "key" not in res and desktop.desktop_live(d)
    assert not api.hello({"on": False})["on"] and not desktop.desktop_live(d)
    (d / "receipts.jsonl").write_text(json.dumps({"type": "reply", "session_id": "s1", "ts": 1, "receipts": [
        {"verdict": "CAP", "kind": "tests", "text": "All tests pass.", "cite": 1, "cmd": "pytest -q", "exit": 1}]})
        + "\n{broken\n", encoding="utf-8")
    view = api.session(id="s1")
    assert view["counts"]["CAP"] == 1 and view["replies"][0]["c"][0]["e"] == 1
    assert api.session(id="nope")["replies"] == []


def test_the_dashboard_router_mounts_the_desktop_routes():
    pytest.importorskip("fastapi")
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("nocap_plugin_api_router_test", root / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(api.router)
    assert {"/board", "/hello", "/verify", "/session"} <= set(app.openapi()["paths"])


def test_session_view_counts_only_what_was_stamped():
    recs = [{"type": "reply", "session_id": "s1", "ts": 1, "receipts": [
        {"verdict": "CAP", "kind": "tests", "text": "a"},
        {"verdict": "NO_RECEIPT", "kind": "deployed", "text": "b", "hidden": True}]},
        {"type": "reply", "session_id": "s1", "ts": 2, "receipts": [
            {"verdict": "NO_RECEIPT", "kind": "url", "text": "c", "hidden": True}]}]
    view = desktop.session_view(recs, "s1")
    assert view["counts"] == {"CAP": 1, "NO_RECEIPT": 0, "NO_CAP": 0} and view["unsure"] == 2
    assert len(view["replies"]) == 1 and [c["t"] for c in view["replies"][0]["c"]] == ["a"]
