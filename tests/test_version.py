"""One version everywhere: plugin.yaml, the package, the dashboard manifest and the newest CHANGELOG entry."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _plugin_yaml_version():
    m = re.search(r'^version:\s*"?([^"\s]+)"?\s*$', (ROOT / "plugin.yaml").read_text(), re.M)
    assert m, "plugin.yaml has no version line"
    return m.group(1)


def _package_version():
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "__init__.py").read_text(), re.M)
    assert m, "__init__.py has no __version__"
    return m.group(1)


def _changelog_top():
    """The newest RELEASED entry. A `## X.Y.Z (unreleased)` heading collects work for the next release and is
    skipped here until the release renames it and bumps plugin.yaml."""
    m = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?(?! \(unreleased\))[ \t]*(?:\(\d{4}-\d{2}-\d{2}\))?[ \t]*$",
                  (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert m, "CHANGELOG.md has no '## <version>' entry"
    return m.group(1)


def test_unreleased_entry_is_newer_than_the_release():
    text = (ROOT / "CHANGELOG.md").read_text()
    pending = re.findall(r"^## (\d+\.\d+\.\d+) \(unreleased\)$", text, re.M)
    assert len(pending) <= 1, pending
    for v in pending:
        assert text.index(f"## {v} (unreleased)") < text.index(f"## {_changelog_top()}")
        assert tuple(map(int, v.split("."))) > tuple(map(int, _plugin_yaml_version().split(".")))


def test_every_version_string_agrees():
    versions = {
        "plugin.yaml": _plugin_yaml_version(),
        "__init__.__version__": _package_version(),
        "dashboard/manifest.json": json.loads((ROOT / "dashboard/manifest.json").read_text())["version"],
        "CHANGELOG.md (newest entry)": _changelog_top(),
    }
    assert len(set(versions.values())) == 1, versions


def test_version_is_0_2_1():
    assert _plugin_yaml_version() == "0.2.1"
