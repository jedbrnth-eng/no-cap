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
    m = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert m, "CHANGELOG.md has no '## <version>' entry"
    return m.group(1)


def test_every_version_string_agrees():
    versions = {
        "plugin.yaml": _plugin_yaml_version(),
        "__init__.__version__": _package_version(),
        "dashboard/manifest.json": json.loads((ROOT / "dashboard/manifest.json").read_text())["version"],
        "CHANGELOG.md (newest entry)": _changelog_top(),
    }
    assert len(set(versions.values())) == 1, versions


def test_version_is_0_2_0():
    assert _plugin_yaml_version() == "0.2.0"
