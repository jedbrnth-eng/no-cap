"""Every local link, image and #anchor in the docs resolves (scripts/check_links.py, offline mode)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _checker():
    spec = importlib.util.spec_from_file_location("check_links", ROOT / "scripts" / "check_links.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docs_links_resolve(capsys):
    assert _checker().main([]) == 0, capsys.readouterr().out


def test_github_anchor_slugs():
    slug = _checker().slug
    assert slug("What it caught") == "what-it-caught"
    assert slug("Known limits and what is not tested") == "known-limits-and-what-is-not-tested"
    assert slug("What 🧾 does and doesn't prove") == "what--does-and-doesnt-prove"
