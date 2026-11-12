"""No Cap + Skim: when No Cap appends its receipts, the body above them still gets Skim's highlighting.

Hermes keeps only the first transform_llm_output rewrite, so on turns where No Cap appends a footer Skim's own
rewrite is dropped. No Cap runs the installed Skim plugin's ``skimlib.glue.transform`` on the body (never the
footer) when Skim is loaded and enabled for the profile. Without Skim everything is byte-identical to before.

The fake Skim below mirrors the real one's contract (``transform(get, response_text=, platform=) -> str | None``,
never raises, None = unchanged). Set NOCAP_TEST_SKIM_DIR to a real Skim checkout to also run the real engine.
"""
import os
import shutil
import sys
import types
from pathlib import Path

import pytest

from test_plugin import FakeCtx, load_plugin, tool

FAKE_GLUE = '''
from .engine import mark

def transform(get, response_text=None, platform="", **_):
    if not isinstance(response_text, str) or not response_text.strip():
        return None
    if get("enabled", True) is False:
        return None
    if (platform or "").lower() in [p.strip() for p in str(get("skip_platforms", "cli")).split(",")]:
        return None
    out = mark(response_text)
    return out if out != response_text else None
'''
FAKE_ENGINE = '''
def mark(text):
    if "**passed**" in text:
        return text
    return text.replace("passed", "**passed**", 1)
'''
MANIFEST = "name: skim\nversion: \"0.1.0\"\nprovides_hooks:\n  - transform_llm_output\n"
BODY = "All 44 tests passed, so the fix is in."


class PeerCtx(FakeCtx):
    def __init__(self, tmp_path, settings=None, loaded=("skim",)):
        super().__init__(tmp_path, settings)
        self.loaded = set(loaded)

    def has_plugin(self, plugin_id):
        return plugin_id in self.loaded


def install_skim(home, glue=FAKE_GLUE, engine=FAKE_ENGINE, dirname="skim"):
    d = Path(home) / "plugins" / dirname
    (d / "skimlib").mkdir(parents=True, exist_ok=True)
    (d / "plugin.yaml").write_text(MANIFEST)
    (d / "__init__.py").write_text("raise RuntimeError('the plugin package itself must never be imported')\n")
    (d / "skimlib" / "__init__.py").write_text("")
    (d / "skimlib" / "glue.py").write_text(glue)
    (d / "skimlib" / "engine.py").write_text(engine)
    return d


@pytest.fixture
def hermes_config(monkeypatch):
    """A fake documented ``hermes_cli.config`` so the plugin reads Skim's settings the way it does in Hermes."""
    cfg = {"plugins": {"enabled": ["no-cap", "skim"], "entries": {}}}
    pkg = types.ModuleType("hermes_cli")
    pkg.__path__ = []
    mod = types.ModuleType("hermes_cli.config")
    mod.load_config_readonly = lambda: cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    return cfg


def run(tmp_path, body=BODY, platform="telegram", skim=True, ctx_cls=PeerCtx, settings=None, **kw):
    mod = load_plugin()
    ctx = ctx_cls(tmp_path, settings or {}, **kw) if ctx_cls is PeerCtx else ctx_cls(tmp_path, settings or {})
    if skim:
        install_skim(tmp_path)  # tmp_path is this fake profile's HERMES_HOME (data_dir.parents[1])
    mod.register(ctx)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    return ctx.hooks["transform_llm_output"](response_text=body, session_id="s1", model="m", platform=platform,
                                             turn_id="t1")


def footer_of(out, body):
    assert out.startswith(body), out
    return out[len(body):]


def test_skim_highlights_the_body_and_the_footer_is_unchanged(tmp_path, hermes_config):
    plain = run(tmp_path / "a", skim=False)
    both = run(tmp_path / "b")
    assert plain is not None and "No Cap" in plain
    skimmed = BODY.replace("passed", "**passed**", 1)
    assert footer_of(both, skimmed) == footer_of(plain, BODY)


def test_without_skim_installed_the_reply_is_byte_identical(tmp_path, hermes_config):
    a = run(tmp_path / "a", skim=False)
    b = run(tmp_path / "b", skim=False, ctx_cls=FakeCtx)  # a host with no has_plugin at all
    assert a == b and a.startswith(BODY + "\n\n")


def test_skim_installed_but_not_loaded_changes_nothing(tmp_path, hermes_config):
    out = run(tmp_path, loaded=())
    assert out.startswith(BODY + "\n\n")


def test_old_host_without_has_plugin_changes_nothing(tmp_path, hermes_config):
    out = run(tmp_path, ctx_cls=FakeCtx)
    assert out.startswith(BODY + "\n\n")


def test_skim_off_in_its_own_settings_means_no_highlighting(tmp_path, hermes_config):
    hermes_config["plugins"]["entries"]["skim"] = {"settings": {"enabled": False}}
    assert run(tmp_path).startswith(BODY + "\n\n")


def test_skim_legacy_config_subtree_is_respected(tmp_path, hermes_config):
    hermes_config["plugins"]["entries"]["skim"] = {"config": {"enabled": False}}
    assert run(tmp_path).startswith(BODY + "\n\n")


def test_skim_skip_platforms_is_respected(tmp_path, hermes_config):
    hermes_config["plugins"]["entries"]["skim"] = {"settings": {"skip_platforms": "telegram"}}
    assert run(tmp_path).startswith(BODY + "\n\n")
    assert run(tmp_path / "cli", platform="cli").startswith(BODY + "\n\n")  # cli skipped by Skim's default


def test_skim_raising_fails_open_to_todays_reply(tmp_path, hermes_config):
    plain = run(tmp_path / "a", skim=False)
    install_skim(tmp_path / "b", glue="def transform(*a, **k):\n    raise ValueError('boom')\n")
    assert run(tmp_path / "b", skim=False) == plain


def test_skim_that_cannot_import_fails_open(tmp_path, hermes_config):
    plain = run(tmp_path / "a", skim=False)
    install_skim(tmp_path / "b", glue="from .missing import nothing\n")
    assert run(tmp_path / "b", skim=False) == plain


def test_skim_returning_junk_fails_open(tmp_path, hermes_config):
    plain = run(tmp_path / "a", skim=False)
    install_skim(tmp_path / "b", glue="def transform(*a, **k):\n    return 42\n")
    assert run(tmp_path / "b", skim=False) == plain


def test_empty_body_is_left_to_hermes(tmp_path, hermes_config):
    assert run(tmp_path, body="") is None
    assert run(tmp_path / "w", body="   \n") is None


def test_no_footer_means_no_rewrite_so_skims_own_hook_still_wins(tmp_path, hermes_config):
    mod = load_plugin()
    ctx = PeerCtx(tmp_path, {})
    install_skim(tmp_path)
    mod.register(ctx)
    out = ctx.hooks["transform_llm_output"](response_text="Hello there, nothing passed here to check.",
                                            session_id="s1", model="m", platform="telegram", turn_id="t1")
    assert out is None


def test_quiet_mode_still_returns_none(tmp_path, hermes_config):
    assert run(tmp_path, settings={"mode": "quiet"}) is None


def test_discord_body_is_highlighted_and_footer_is_the_discord_footer(tmp_path, hermes_config):
    plain = run(tmp_path / "a", skim=False, platform="discord")
    both = run(tmp_path / "b", platform="discord")
    skimmed = BODY.replace("passed", "**passed**", 1)
    assert footer_of(both, skimmed) == footer_of(plain, BODY)


def test_skim_dir_found_by_manifest_name_not_folder_name(tmp_path, hermes_config):
    install_skim(tmp_path, dirname="hermes-skim")
    out = run(tmp_path, skim=False)
    assert out.startswith(BODY.replace("passed", "**passed**", 1) + "\n\n")


def test_plugin_package_is_never_imported_and_sys_modules_stay_clean(tmp_path, hermes_config):
    before = set(sys.modules)
    run(tmp_path)
    new = {m for m in set(sys.modules) - before if "skim" in m.lower()}
    assert not any(m == "skimlib" or m.startswith("skimlib.") for m in new)
    assert all(m.startswith("_nocap_peer_skim_") for m in new), new


def test_skims_own_hook_leaves_a_body_no_cap_highlighted_unchanged(tmp_path, hermes_config):
    both = run(tmp_path)
    body = both[:both.index("\n\n")]
    glue = sys.modules[[m for m in sys.modules if m.startswith("_nocap_peer_skim_") and m.endswith(".glue")][0]]
    assert glue.transform(lambda k, d=None: d, response_text=body, platform="telegram") is None


# ---- the real Skim engine (opt-in: NOCAP_TEST_SKIM_DIR=<skim checkout>) ---------------------------------------------
REAL = os.environ.get("NOCAP_TEST_SKIM_DIR", "")
real = pytest.mark.skipif(not (REAL and Path(REAL, "skimlib", "glue.py").is_file()),
                          reason="set NOCAP_TEST_SKIM_DIR to a Skim checkout")
LONG = "\n".join([
    "Status: done. All 44 tests passed and the build is green.",
    "",
    "You need to restart the gateway before Friday, otherwise the old hook stays loaded.",
    "",
    "```python",
    "print('44 passed')  # code is never bolded",
    "```",
    "",
] + [f"Line {i}: the change touched 3 files and saved 12% of the runtime." for i in range(12)])


def run_real(tmp_path, body, platform):
    mod = load_plugin()
    ctx = PeerCtx(tmp_path, {})
    dst = Path(tmp_path) / "plugins" / "skim"
    shutil.copytree(REAL, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests", "proof"))
    mod.register(ctx)
    tool(ctx, "pytest -q", "44 passed in 0.5s")
    return ctx.hooks["transform_llm_output"](response_text=body, session_id="s1", model="m", platform=platform,
                                             turn_id="t1")


@real
@pytest.mark.parametrize("platform", ["telegram", "discord"])
def test_real_skim_highlights_body_with_tldr_and_keeps_code_and_footer(tmp_path, hermes_config, platform):
    plain = run(tmp_path / "a", body=LONG, skim=False, platform=platform)
    both = run_real(tmp_path / "b", LONG, platform)
    assert both.startswith("**TL;DR:**") and "**" in both.split("```")[0]
    assert "print('44 passed')  # code is never bolded" in both
    foot = footer_of(plain, LONG)
    assert both.endswith(foot)
    body = both[:-len(foot)]
    glue = sys.modules[[m for m in sys.modules if m.startswith("_nocap_peer_skim_") and m.endswith(".glue")][-1]]
    assert glue.transform(lambda k, d=None: d, response_text=body, platform=platform) is None  # idempotent


def test_doctor_reports_skim_as_composed_not_as_a_conflict(tmp_path):
    from test_doctor import doctor_mod
    home = tmp_path / "home"
    install_skim(home)
    text, n = doctor_mod().check(home, "annotate", {}, tmp_path / "data" / "receipts.jsonl", [], lambda name: None)
    assert n == 0 and "Skim" in text and "highlighting" in text
    assert "Other reply transforms installed" not in text


def test_doctor_still_flags_other_rewriters_next_to_skim(tmp_path):
    from test_doctor import doctor_mod
    home = tmp_path / "home"
    install_skim(home)
    other = home / "plugins" / "turn-usage"
    other.mkdir(parents=True)
    (other / "plugin.yaml").write_text("name: turn-usage\nprovides_hooks:\n  - transform_llm_output\n")
    text, n = doctor_mod().check(home, "annotate", {}, tmp_path / "data" / "receipts.jsonl", [], lambda name: None)
    assert n == 1 and "turn-usage" in text.split("Other reply transforms installed")[1].split("\n")[0]
    assert "skim" not in text.split("Other reply transforms installed")[1].split("\n")[0]
