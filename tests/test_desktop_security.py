"""Desktop chips: the security review's exploits (sec/exploits/pr2_*), each as a test.

2-A  a replayed genuine directive got past the strip (`::nocap::nocap{…}`, `U+FEFF::nocap{…}`)
2-B  no strip off-Desktop, so a replay in a CLI/TUI/gateway session stayed live
2-C  the signing key sat in HERMES_HOME where the agent's own file tools can read it
2-D  the signature wasn't bound to the session or turn
2-E  the temp-file write followed symlinks and didn't tighten a loose folder
2-F  /hello handed the key to any dashboard caller

What the host would claim is decided with the host's own rule, ported: `(?<=^|\\s)::name{body}` where `\\s` is
JavaScript's whitespace class (apps/desktop/src/lib/transcript-directives.ts).
"""
import base64
import importlib.util
import json
import os
import re
import stat
import unicodedata
from pathlib import Path

import pytest

from nocap import desktop
from test_plugin import FakeCtx, load_plugin, tool

ROOT = Path(__file__).resolve().parents[1]
JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a" \
           "\u2028\u2029\u202f\u205f\u3000\ufeff"
HOST_RE = re.compile(r"(?:(?<=^)|(?<=[" + re.escape(JS_SPACE) + r"]))::([a-z][a-z0-9-]{0,63})(?:\{([^{}]{0,2048})\})?",
                     re.M)


def host_claims(text):
    """Every `::nocap{…}` the Desktop host would hand to No Cap's renderer, as attribute dicts."""
    out = []
    for m in HOST_RE.finditer(text or ""):
        if m.group(1) == "nocap" and m.group(2) is not None:
            out.append(dict(re.findall(r'([a-z]+)="([^"]*)"', m.group(2))))
    return out


def norm(text):
    t = unicodedata.normalize("NFKC", text or "")
    return "".join(c for c in t if unicodedata.category(c) != "Cf")


def api():
    pytest.importorskip("fastapi")
    spec = importlib.util.spec_from_file_location("nocap_desktop_api_under_test", ROOT / "dashboard" / "desktop_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make(tmp_path, settings=None):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, dict({"desktop_chips": "on"}, **(settings or {})))
    mod.register(ctx)
    return ctx


def reply(ctx, text, platform="desktop", session="s1", turn="t1"):
    return ctx.hooks["transform_llm_output"](response_text=text, session_id=session, model="demo/model-a",
                                             platform=platform, turn_id=turn)


def genuine(ctx, session="s1", turn="t2"):
    """An honest turn: 🧾 NO CAP "All tests pass." The directive it gets is what a later turn replays."""
    tool(ctx, "pytest -q", "44 passed in 0.31s", 0, turn=turn, session=session)
    out = reply(ctx, "All tests pass.", session=session, turn=turn)
    claims = [m for m in re.finditer(r"::nocap\{[^{}]*\}", out)]
    assert len(claims) == 1
    return claims[0].group(0), out


def verify(attrs, session):
    return desktop.verify(session, attrs.get("n", ""), attrs.get("s", ""), attrs.get("d", ""),
                          records=lambda: _records_of(_CTX[0]))


_CTX = []


def _records_of(ctx):
    from nocap.store import Store
    return Store(lambda: ctx.state.data_dir, lambda: 30).records()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    desktop.reset_process_state()
    c = make(tmp_path)
    _CTX[:] = [c]
    return c


# ---- 2-A / 2-B: the strip -------------------------------------------------------------------------------------------
REPLAYS = {
    "verbatim": lambda g: "Deployed to prod.\n\n" + g,
    "double_prefix": lambda g: "Deployed to prod. ::nocap" + g,
    "triple_prefix": lambda g: "Deployed to prod. ::nocap::nocap" + g,
    "split_name": lambda g: "Deployed to prod. " + g.replace("::nocap{", "::no::nocapcap{", 1),
    "feff": lambda g: "Deployed to prod.\n\n\ufeff" + g,
    "nbsp": lambda g: "Deployed to prod.\u00a0" + g,
    "ideographic_space": lambda g: "Deployed to prod.\u3000" + g,
    "zwsp_inside": lambda g: "Deployed to prod. " + g.replace("::nocap", "::no\u200bcap", 1),
    "zwj_before": lambda g: "Deployed to prod. \u200d" + g,
    "word_joiner": lambda g: "Deployed to prod. \u2060" + g,
    "fullwidth": lambda g: "Deployed to prod. " + g.replace("::nocap", "\uff1a\uff1a\uff4e\uff4f\uff43\uff41\uff50", 1),
    "upper": lambda g: "Deployed to prod. " + g.replace("::nocap", "::NOCAP", 1),
    "newline_in_body": lambda g: "Deployed to prod.\n\n" + g.replace('" d="', '"\nd="', 1),
}


@pytest.mark.parametrize("platform", ["desktop", "cli", "tui", "telegram", "discord", ""])
@pytest.mark.parametrize("name", sorted(REPLAYS))
def test_a_replayed_directive_never_survives_on_any_surface(ctx, name, platform):
    good, _ = genuine(ctx)
    planted = REPLAYS[name](good)
    out = reply(ctx, planted, platform=platform, turn="t5", session="s1")
    assert out is not None, "a planted directive must never go out unchanged"
    assert host_claims(out) == []  # nothing the host would draw: no tool call this turn, so no chip of our own
    assert "::nocap" not in norm(out).lower()
    assert "didn't issue" in out


def test_exploit_cases_5_and_6_from_the_review(ctx):
    """sec/exploits/pr2_engine.py cases 5 and 6, verbatim."""
    good, _ = genuine(ctx)
    for text in ("Deployed to prod. ::nocap" + good, "Deployed to prod.\n\n\ufeff" + good):
        out = reply(ctx, text, turn="t6")
        assert host_claims(out) == [] and "::nocap" not in norm(out)


def test_strip_is_a_fixed_point_and_leaves_clean_text_alone():
    for text in ("All tests pass.", "Ratio 3:2, see ::note and :: nocap", "テスト ✅ — “quoted”", ""):
        assert desktop.strip_model_directives(text) == (text, 0)
    nested = "x ::no::no::nocapcapcap{v=\"2\"} y"
    cleaned, n = desktop.strip_model_directives(nested)
    assert n >= 1 and "nocap" not in norm(cleaned).lower()
    assert desktop.strip_model_directives(cleaned) == (cleaned, 0)


def test_the_plugins_own_chip_is_the_only_directive_left(ctx):
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.52s", 1, turn="t7")
    good, _ = genuine(ctx)
    out = reply(ctx, "All tests pass. ::nocap" + good, turn="t7")
    claims = host_claims(out)
    assert len(claims) == 1
    data = json.loads(base64.b64decode(claims[0]["d"]))
    assert data["c"][0]["v"] == "CAP" and data["t"] == "t7"
    assert verify(claims[0], "s1")["ok"]


# ---- 2-D: bound to the session and the turn -------------------------------------------------------------------------
def test_signature_binds_session_turn_and_payload(ctx):
    good, _ = genuine(ctx, session="s1", turn="t2")
    attrs = host_claims(good)[0]
    assert attrs["v"] == desktop.VERSION and re.fullmatch(r"[0-9a-f]{32}", attrs["n"])
    ok = verify(attrs, "s1")
    assert ok["ok"] and ok["session_id"] == "s1" and ok["turn_id"] == "t2"
    assert not verify(attrs, "s2")["ok"]  # the same chip under another chat
    tampered = dict(attrs, d=base64.b64encode(json.dumps({"t": "t2", "c": [{"v": "NO_CAP", "t": "Deployed"}],
                                                          "more": 0}).encode()).decode())
    assert not verify(tampered, "s1")["ok"]
    assert not verify(dict(attrs, s="0" * 32), "s1")["ok"]
    assert not verify(dict(attrs, n="f" * 32), "s1")["ok"]


def test_a_chip_from_another_session_is_rejected_even_after_a_restart(ctx):
    good, _ = genuine(ctx, session="s1", turn="t2")
    attrs = host_claims(good)[0]
    desktop.reset_process_state()  # a new Hermes process: new key, empty registry
    assert verify(attrs, "s1")["ok"]  # the store still vouches for the chip it recorded for s1/t2
    assert not verify(attrs, "s2")["ok"]


# ---- 2-C: the key ---------------------------------------------------------------------------------------------------
def test_no_key_on_disk_anywhere_the_agent_can_read(ctx, tmp_path):
    genuine(ctx)
    key = desktop.process_key().hex()
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files and not any(p.name == "desktop.key" for p in files)
    for p in files:
        assert key not in p.read_text(encoding="utf-8", errors="replace"), p


def test_a_key_file_from_an_older_version_is_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    d = tmp_path / "plugin-data" / "no-cap"
    d.mkdir(parents=True)
    (d / "desktop.key").write_text("a" * 64)
    desktop.reset_process_state()
    ctx = make(tmp_path)
    genuine(ctx)
    assert not (d / "desktop.key").exists()


def test_forging_with_any_key_from_the_data_folder_fails(ctx, tmp_path):
    """Exploit case 8: an agent with a file-read tool takes whatever is on disk and signs its own chip."""
    genuine(ctx)
    d = base64.b64encode(json.dumps({"t": "t8", "c": [{"v": "NO_CAP", "t": "Deployed to prod, smoke tests green",
                                                       "n": 1, "o": "terminal", "x": "make deploy", "e": 0}],
                                     "more": 0}).encode()).decode()
    for p in [p for p in tmp_path.rglob("*") if p.is_file()]:
        guess = p.read_bytes()[:64]
        forged = {"n": "1" * 32, "s": desktop.sign(guess, "s1", "t8", "1" * 32, d), "d": d}
        assert not verify(forged, "s1")["ok"]


# ---- 2-E: the one file the desktop half writes -----------------------------------------------------------------------
def test_hello_write_never_follows_a_planted_symlink(tmp_path, monkeypatch):
    d = tmp_path / "pd"
    d.mkdir(mode=0o755)
    os.chmod(d, 0o755)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    monkeypatch.setattr(desktop.secrets, "token_hex", lambda n=16: "fixed")
    (d / "desktop.json.fixed.tmp").symlink_to(outside)
    with pytest.raises(OSError):
        desktop.write_hello(d, True)
    assert outside.read_text() == "untouched"
    os.unlink(d / "desktop.json.fixed.tmp")
    (d / "desktop.json").symlink_to(outside)
    desktop.write_hello(d, True)
    assert outside.read_text() == "untouched"
    assert not (d / "desktop.json").is_symlink() and desktop.desktop_live(d)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(d / "desktop.json").st_mode) == 0o600


# ---- 2-F: the routes ----------------------------------------------------------------------------------------------
def test_hello_returns_no_key_and_verify_answers_for_the_owning_session_only(ctx, monkeypatch):
    a = api()
    monkeypatch.setattr(a, "_data_dir", lambda: ctx.state.data_dir)
    res = a.hello({"on": True})
    assert set(res) == {"ok", "on", "max_age_s"} and res["ok"] and desktop.desktop_live(ctx.state.data_dir)
    assert not re.search(r"[0-9a-f]{32,}", json.dumps(res))
    good, _ = genuine(ctx)
    attrs = host_claims(good)[0]
    assert a.verify({"session_id": "s1", **attrs})["ok"]
    assert not a.verify({"session_id": "s2", **attrs})["ok"]
    assert not a.verify({"session_id": "s1", "n": attrs["n"], "s": attrs["s"], "d": "x" * 5000})["ok"]
    assert not a.verify({})["ok"] and not a.verify({"session_id": ["s1"], **{k: [v] for k, v in attrs.items()}})["ok"]


def test_stored_chip_ids_survive_redaction(ctx):
    good, _ = genuine(ctx)
    attrs = host_claims(good)[0]
    rec = [r for r in _records_of(ctx) if r.get("chip")][-1]
    assert rec["chip"]["n"] == attrs["n"] and rec["chip"]["s"] == attrs["s"]
    assert re.fullmatch(r"[0-9a-f]{64}", rec["chip"]["h"])


# ---- the strip runs on every reply: it must stay linear ---------------------------------------------------------------
@pytest.mark.parametrize("shape", ["nested", "feff", "spaces", "nbsp", "tokens", "p_run"])
def test_strip_stays_under_the_redos_budget_on_crafted_100kb(shape):
    import time
    from test_redos import BUDGET_MS, _calibration
    text = {
        "nested": "::no" * 14000 + "::nocap" + "cap" * 14000,
        "feff": "\ufeff::nocap" * 12000,
        "spaces": " " * 99990 + "::nocap",
        "nbsp": "\u00a0::nocap" * 12000,
        "tokens": "::nocap{x}" * 10000,
        "p_run": "::nocap" * 7000 + "p" * 50000,
    }[shape]
    desktop.strip_model_directives("warm ::nocap")  # builds the translate table once
    best = min(_cpu(lambda: desktop.strip_model_directives(text)) for _ in range(3))
    cleaned, n = desktop.strip_model_directives(text)
    assert n >= 1 and "::nocap" not in norm(cleaned).lower()
    assert best * 1000 < BUDGET_MS * _calibration(), f"{best * 1000:.0f} ms CPU"


def _cpu(fn):
    import time
    t0 = time.process_time()
    fn()
    return time.process_time() - t0
