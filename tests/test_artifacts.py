"""Fabricated-artifact detector: a claimed SHA or branch that doesn't exist in the session's repo gets 🧢, a claimed
PR number that no gh output this session shows gets 🤔. Read-only, hardened git (an untrusted repo can't run code)."""
import json
import os
import subprocess

import pytest

from nocap.engine import Engine
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT
from nocap import verify

FAKE40 = "1234567890abcdef1234567890abcdef12345678"


def git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                           "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True, timeout=30).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "first")
    git(r, "branch", "feat/real")
    git(r, "update-ref", "refs/remotes/origin/feat/remote-only", "HEAD")
    return r


def engine(d, cwd, **settings):
    settings.setdefault("show_uncertain", "all")
    return Engine(lambda: d, lambda k, default=None: settings.get(k, default), cwd=lambda: str(cwd))


def reply(e, text, sid="s", tid="t1"):
    out = e.on_reply(response_text=text, session_id=sid, turn_id=tid, model="m", platform="cli")
    rec = e.store.last(sid)
    return out, (rec or {}).get("receipts", [])


def test_fabricated_full_sha_is_cap(tmp_path, repo):
    out, rs = reply(engine(tmp_path / "d", repo), f"Committed the fix as {FAKE40}.")
    r = [x for x in rs if x["kind"] in ("sha", "committed")][0]
    assert r["verdict"] == CAP and r["why"] == "sha not found in repo"
    assert "🧢 CAP" in out and "sha not found in repo" in out


def test_fabricated_short_sha_is_cap_and_real_one_is_not(tmp_path, repo):
    head = git(repo, "rev-parse", "HEAD")
    _, rs = reply(engine(tmp_path / "d", repo), "The fix is commit 9f8e7d6.")
    assert [x["verdict"] for x in rs if x["kind"] == "sha"] == [CAP]
    _, rs = reply(engine(tmp_path / "d2", repo), f"The fix is commit {head[:8]}.")
    assert all(x["verdict"] != CAP for x in rs)


def test_hash_that_is_not_a_commit_is_left_alone(tmp_path, repo):
    _, rs = reply(engine(tmp_path / "d", repo), "The md5 checksum of the build is 9e107d9d372bb6826bd81d3542a419d6.")
    assert all(x["verdict"] != CAP for x in rs)


def test_sha_seen_in_a_tool_output_is_never_fabricated(tmp_path, repo):
    e = engine(tmp_path / "d", repo)
    e.on_tool(tool_name="terminal", args={"command": "git log -1 --format=%H"},
              result=json.dumps({"output": FAKE40, "exit_code": 0}), session_id="s", turn_id="t1")
    _, rs = reply(e, f"I committed {FAKE40[:7]} earlier.")
    assert all(x["verdict"] != CAP for x in rs)


def test_fabricated_branch_is_cap_real_ones_are_not(tmp_path, repo):
    _, rs = reply(engine(tmp_path / "d", repo), "Pushed to feat/made-up-login.")
    r = [x for x in rs if x["kind"] == "pushed"][0]
    assert r["verdict"] == CAP and "branch feat/made-up-login not found" in r["why"]
    for b in ("feat/real", "feat/remote-only", "main"):
        _, rs = reply(engine(tmp_path / ("d-" + b.replace("/", "-")), repo), f"Pushed to {b}.")
        assert all(x["verdict"] != CAP for x in rs), b


def test_branch_named_in_a_command_is_left_alone(tmp_path, repo):
    """It may have been deleted after the merge (`git push origin --delete feat/x`)."""
    e = engine(tmp_path / "d", repo)
    e.on_tool(tool_name="terminal", args={"command": "git push origin --delete feat/gone"},
              result=json.dumps({"output": " - [deleted]  feat/gone", "exit_code": 0}), session_id="s", turn_id="t1")
    _, rs = reply(e, "Pushed to feat/gone.")
    assert all(x["verdict"] != CAP for x in rs)


def test_opt_out_and_no_cwd(tmp_path, repo):
    _, rs = reply(engine(tmp_path / "d", repo, verify_artifacts=False), f"Committed {FAKE40}.")
    assert all(x["verdict"] != CAP for x in rs)
    _, rs = reply(engine(tmp_path / "d2", ""), f"Committed {FAKE40}.")
    assert all(x["verdict"] != CAP for x in rs)


def test_other_repo_in_the_session_disables_it(tmp_path, repo):
    e = engine(tmp_path / "d", repo)
    e.on_tool(tool_name="terminal", args={"command": "cd /srv/other && git log -1"},
              result=json.dumps({"output": "commit x", "exit_code": 0}), session_id="s", turn_id="t1")
    _, rs = reply(e, f"Committed {FAKE40}.")
    assert all(x["verdict"] != CAP for x in rs)


def test_shallow_repo_is_not_checked(tmp_path, repo):
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow))
    _, rs = reply(engine(tmp_path / "d", shallow), f"Committed {FAKE40}.")
    assert all(x["verdict"] != CAP for x in rs)


def test_not_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    _, rs = reply(engine(tmp_path / "d", plain), f"Committed {FAKE40}. Pushed to feat/nope.")
    assert all(x["verdict"] != CAP for x in rs)


def test_malicious_repo_config_runs_nothing(tmp_path, repo, monkeypatch):
    """A hostile .git/config (fsmonitor, hooks, pager, aliases, sshCommand, an include) must not run anything, and
    a GIT_DIR exported into the environment must not redirect the check."""
    marker = tmp_path / "PWNED"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for h in ("post-checkout", "pre-commit", "reference-transaction", "post-index-change", "fsmonitor-watchman"):
        (hooks / h).write_text(f"#!/bin/sh\ntouch {marker}-{h}\n")
        (hooks / h).chmod(0o755)
    evil = tmp_path / "evil.cfg"
    evil.write_text(f"[core]\n\tfsmonitor = touch {marker}-include\n")
    with open(repo / ".git" / "config", "a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}-fsmonitor\n\thooksPath = {hooks}\n\tpager = touch {marker}-pager\n"
                 f"\tsshCommand = touch {marker}-ssh\n[alias]\n\tcat-file = !touch {marker}-alias\n"
                 f"[include]\n\tpath = {evil}\n[diff]\n\texternal = touch {marker}-diff\n")
    # control: the trap is armed (plain `git status` runs the fsmonitor command), so the checks below mean something
    subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, timeout=30,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull))
    armed = list(tmp_path.glob("PWNED*"))
    assert armed, "the malicious config didn't fire even unhardened; the test proves nothing"
    for m in armed:
        m.unlink()
    res = verify.run_git(str(repo), ["status", "--porcelain"])  # the same command through the hardened plumbing
    assert res is not None and res[0] == 0
    assert not list(tmp_path.glob("PWNED*"))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(evil))
    e = engine(tmp_path / "d", repo)
    _, rs = reply(e, f"Committed {FAKE40}. Pushed to feat/made-up-login.")
    assert {x["kind"]: x["verdict"] for x in rs}.get("pushed") == CAP  # the check still worked
    assert verify.recheck({"kind": "sha", "verdict": NO_RECEIPT, "claim": {"sha": FAKE40}}, str(repo)) is None
    assert not list(tmp_path.glob("PWNED*")), list(tmp_path.glob("PWNED*"))


def test_git_env_and_argv_are_hardened(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/x")
    monkeypatch.setenv("GIT_EXEC_PATH", "/x")
    env = verify.git_env()
    assert "GIT_DIR" not in env and "GIT_EXEC_PATH" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull and env["GIT_NO_LAZY_FETCH"] == "1"
    for flag in ("core.hooksPath=/dev/null", "core.fsmonitor=false", "protocol.allow=never"):
        assert flag in verify.HARDEN


# ---- PR numbers: ledger only, no git --------------------------------------------------------------------------
def _gh(e, cmd, out, code=0, tid="t1", tool="terminal"):
    e.on_tool(tool_name=tool, args={"command": cmd}, result=json.dumps({"output": out, "exit_code": code}),
              session_id="s", turn_id=tid)
    e.on_reply(response_text="Checked.", session_id="s", turn_id=tid, model="m", platform="cli")


def test_pr_never_shown_is_no_receipt(tmp_path):
    e = engine(tmp_path, "")
    _, rs = reply(e, "Merged PR #42.", tid="t2")
    assert [(x["kind"], x["verdict"], x["why"]) for x in rs] == [("merged", NO_RECEIPT, "no gh output this session shows #42")]


def test_pr_open_in_an_earlier_turn_is_cap(tmp_path):
    e = engine(tmp_path, "")
    _gh(e, "gh pr view 42 --json state", '{"state":"OPEN"}')
    out, rs = reply(e, "Merged PR #42.", tid="t2")
    assert rs[0]["verdict"] == CAP and rs[0]["turn"] == 1 and "turn 1" in out


def test_pr_missing_is_cap_for_opened_and_merged(tmp_path):
    e = engine(tmp_path, "")
    _gh(e, "gh pr view 42", "GraphQL: Could not resolve to a PullRequest with the number of 42. (repository.pullRequest)", 1)
    _, rs = reply(e, "I opened PR #42 and merged PR #42.", tid="t2")
    assert sorted((x["kind"], x["verdict"]) for x in rs) == [("merged", CAP), ("pr_opened", CAP)]


def test_pr_merged_earlier_is_a_receipt(tmp_path):
    e = engine(tmp_path, "")
    _gh(e, "gh pr merge 12 --squash", "✓ Squashed and merged pull request #12")
    _, rs = reply(e, "Merged PR #12.", tid="t2")
    assert rs[0]["verdict"] == NO_CAP and rs[0]["turn"] == 1


def test_github_tool_other_than_gh_vetoes_the_cap(tmp_path):
    e = engine(tmp_path, "")
    _gh(e, "gh pr view 42 --json state", '{"state":"OPEN"}')
    e.on_tool(tool_name="mcp_github_merge_pull_request", args={"pull_number": 42}, result=json.dumps({"merged": True}),
              session_id="s", turn_id="t2")
    _, rs = reply(e, "Merged PR #42.", tid="t2")
    assert rs[0]["verdict"] != CAP
