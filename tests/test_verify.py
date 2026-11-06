import subprocess

import pytest

from nocap import verify
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT


def rec(kind, text="x", **claim):
    return {"kind": kind, "text": text, "verdict": NO_RECEIPT, "claim": {"kind": kind, **claim}}


def test_file_exists_flips(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello")
    assert verify.recheck(rec("file", "Created docs/a.md", path="docs/a.md"), str(tmp_path))[0] == NO_CAP


def test_existing_file_does_not_prove_an_edit_claim(tmp_path):
    (tmp_path / "auth.py").write_text("x")  # found by the e2e demo: "Fixed the bug in auth.py" got 🧾 for existing
    assert verify.recheck(rec("file", "Fixed the login bug in `auth.py`.", path="auth.py"), str(tmp_path)) is None


def test_recheck_never_overrules_a_cap(repo):
    path, _, git = repo  # origin/main == main locally, but this turn's push went elsewhere: the 🧢 stands
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    r = dict(rec("pushed", "pushed to main", branch="main"), verdict=CAP)
    assert verify.recheck(r, str(path)) is None
    assert verify.recheck(rec("pushed", "pushed to main", branch="main"), str(path))[0] == NO_CAP


def test_missing_file_is_not_a_cap(tmp_path):
    assert verify.recheck(rec("file", path="docs/nope.md"), str(tmp_path)) is None


def test_relative_path_without_cwd_is_skipped():
    assert verify.recheck(rec("file", path="docs/a.md"), "") is None


@pytest.fixture
def repo(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout
    git("init", "-q", "-b", "main")
    (tmp_path / "f").write_text("1")
    git("add", "f")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    sha = git("rev-parse", "HEAD").strip()
    return tmp_path, sha, git


def test_sha_exists_flips(repo):
    path, sha, _ = repo
    assert verify.recheck(rec("sha", sha=sha[:7]), str(path))[0] == NO_CAP
    assert verify.recheck(rec("sha", sha="abc1234"), str(path)) is None


def test_push_tracking_ref(repo):
    path, sha, git = repo
    assert verify.recheck(rec("pushed", branch="main"), str(path)) is None
    git("update-ref", "refs/remotes/origin/main", sha)
    assert verify.recheck(rec("pushed", branch="main"), str(path))[0] == NO_CAP


def test_option_like_branch_is_refused(repo, monkeypatch):
    path, _, _ = repo
    calls = []
    monkeypatch.setattr(verify.subprocess, "run", lambda argv, **k: calls.append(argv))
    assert verify.recheck(rec("pushed", branch="--output=/tmp/x"), str(path)) is None
    assert calls == []


def test_only_allowlisted_git_runs(repo, monkeypatch):
    path, sha, _ = repo
    seen = []
    real = subprocess.run

    def spy(argv, **k):
        seen.append(argv)
        return real(argv, **k)

    monkeypatch.setattr(verify.subprocess, "run", spy)
    for r in (rec("sha", sha=sha[:7]), rec("pushed", branch="main"), rec("tests"), rec("merged", pr=3),
              rec("deployed"), rec("number", value="3")):
        verify.recheck(r, str(path))
    sub = lambda a: tuple(a[a.index("-C") + 2:a.index("-C") + 4])  # after the hardening flags and -C <cwd>
    assert seen and all(a[0] == "git" and sub(a) in verify.READ_ONLY_GIT for a in seen)
    assert all("core.hooksPath=/dev/null" in a and "core.fsmonitor=false" in a for a in seen)


def test_url_needs_opt_in(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert verify.recheck(rec("url", url="https://example.com"), "", allow_http=False) is None


def test_url_head_404_is_cap(monkeypatch):
    monkeypatch.setattr(verify, "http_head", lambda url: 404)
    assert verify.recheck(rec("url", url="https://example.com/x"), "", allow_http=True)[0] == CAP


def test_suggestions_name_the_check():
    assert "pytest -q" in verify.suggestion(rec("tests"), ["pytest -q"])
    assert "gh pr view 7" in verify.suggestion(rec("merged", pr=7), [])
