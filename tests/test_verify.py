import os
import subprocess
import time

import pytest

from nocap import verify
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT


def rec(kind, text="x", **claim):
    return {"kind": kind, "text": text, "verdict": NO_RECEIPT, "claim": {"kind": kind, **claim}}


def sess(start=None, *calls):
    return {"start": start, "calls": list(calls)}


def test_file_exists_flips_only_for_this_sessions_work(tmp_path):
    """S6: "created X" needs X written by a call this session, or an mtime after the session started."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello")
    r = rec("file", "Created docs/a.md", path="docs/a.md")
    assert verify.recheck(r, str(tmp_path)) is None                                      # no session: no proof
    assert verify.recheck(r, str(tmp_path), session=sess(time.time() + 60)) is None      # older than the session
    assert verify.recheck(r, str(tmp_path), session=sess(time.time() - 60))[0] == NO_CAP  # made during it
    old = sess(time.time() + 60, {"i": 1, "ok": True, "paths_edited": ["docs/a.md"]})
    got = verify.recheck(r, str(tmp_path), session=old)
    assert got[0] == NO_CAP and "written by a call this session" in got[1]


def test_preexisting_readme_is_not_a_receipt(tmp_path):
    (tmp_path / "README.md").write_text("# old")
    os.utime(tmp_path / "README.md", (1_000_000_000, 1_000_000_000))
    r = rec("file", "I created README.md", path="README.md")
    assert verify.recheck(r, str(tmp_path), session=sess(time.time() - 3600)) is None


def test_deleted_file_needs_a_delete_in_the_session(tmp_path):
    r = rec("file", "Deleted docs/old.md", path="docs/old.md")
    assert verify.recheck(r, str(tmp_path), session=sess(time.time() - 60)) is None
    rm = {"i": 2, "ok": True, "paths_edited": ["docs/old.md"]}
    assert verify.recheck(r, str(tmp_path), session=sess(time.time() - 60, rm))[0] == NO_CAP


def test_existing_file_does_not_prove_an_edit_claim(tmp_path):
    (tmp_path / "auth.py").write_text("x")  # found by the e2e demo: "Fixed the bug in auth.py" got 🧾 for existing
    assert verify.recheck(rec("file", "Fixed the login bug in `auth.py`.", path="auth.py"), str(tmp_path)) is None


def test_recheck_never_overrules_a_cap(repo):
    path, _, git = repo  # origin/main == main locally, but this turn's push went elsewhere: the 🧢 stands
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    r = dict(rec("pushed", "pushed to main", branch="main"), verdict=CAP)
    assert verify.recheck(r, str(path), session=sess(0, PUSH_MAIN)) is None
    assert verify.recheck(rec("pushed", "pushed to main", branch="main"), str(path), session=sess(0, PUSH_MAIN))[0] == NO_CAP


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


def test_sha_flips_only_for_a_new_commit_on_head(repo):
    path, sha, git = repo
    assert verify.recheck(rec("sha", sha=sha[:7]), str(path)) is None                     # no session: no proof
    assert verify.recheck(rec("sha", sha=sha[:7]), str(path), session=sess(time.time() - 60))[0] == NO_CAP
    assert verify.recheck(rec("sha", sha=sha[:7]), str(path), session=sess(time.time() + 600)) is None  # older
    seen = sess(time.time() + 600, {"i": 1, "ok": True, "shas": [sha]})
    assert verify.recheck(rec("sha", sha=sha[:7]), str(path), session=seen)[0] == NO_CAP   # the session showed it
    assert verify.recheck(rec("sha", sha="abc1234"), str(path), session=sess(0)) is None


def test_sha_off_head_is_not_a_receipt(repo):
    path, sha, git = repo
    git("checkout", "-qb", "side")
    (path / "g").write_text("2")
    git("add", "g")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "side")
    side = git("rev-parse", "HEAD").strip()
    git("checkout", "-q", "main")
    assert verify.recheck(rec("sha", sha=side[:7]), str(path), session=sess(time.time() - 60)) is None


PUSH_MAIN = {"i": 3, "ok": True, "cmd": "git push origin main", "git": {"push_ok": True, "push_refs": ["main"]}}


def test_stale_tracking_ref_is_not_a_push(repo):
    path, sha, git = repo
    assert verify.recheck(rec("pushed", branch="main"), str(path), session=sess(0)) is None
    git("update-ref", "refs/remotes/origin/main", sha)          # equal refs from an earlier fetch, no push
    assert verify.recheck(rec("pushed", branch="main"), str(path), session=sess(time.time() - 60)) is None
    got = verify.recheck(rec("pushed", branch="main"), str(path), session=sess(time.time() - 60, PUSH_MAIN))
    assert got[0] == NO_CAP and "pushed by a call this session" in got[1]


def test_push_seen_in_the_tracking_reflog(repo, tmp_path_factory):
    path, sha, git = repo
    origin = tmp_path_factory.mktemp("origin") / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    git("remote", "add", "origin", str(origin))
    git("-c", "core.logAllRefUpdates=true", "push", "-q", "origin", "main")
    r = rec("pushed", branch="main")
    got = verify.recheck(r, str(path), session=sess(time.time() - 60))
    assert got and got[0] == NO_CAP and "reflog" in got[1]
    assert verify.recheck(r, str(path), session=sess(time.time() + 600)) is None  # that push predates the session


def test_session_context_reads_the_ledger():
    hist = [{"turn": 1, "calls": [{"i": 1, "ts": 1000.0}, {"i": 2, "ts": 1010.0}]}, {"turn": 2, "calls": [{"i": 1}]}]
    ctx = verify.session_context(hist)
    assert ctx["start"] == 1000.0 - verify.SESSION_SLACK and len(ctx["calls"]) == 3
    assert verify.session_context([])["start"] is None


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
        verify.recheck(r, str(path), session=sess(0))
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
