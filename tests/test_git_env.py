"""The git child gets a minimal environment, never the agent's provider keys (catalog review, PR #149272)."""
import os

import pytest

from nocap import verify


def test_git_env_drops_secrets_and_keeps_only_allowlisted(monkeypatch):
    for k, v in {"OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "a", "GITHUB_TOKEN": "g", "AWS_SECRET_ACCESS_KEY": "s",
                 "HERMES_HOME": "/tmp/h", "GIT_DIR": "/evil", "PATH": "/usr/bin:/bin", "HOME": "/tmp/home",
                 "LANG": "en_US.UTF-8", "LC_ALL": "C"}.items():
        monkeypatch.setenv(k, v)
    env = verify.git_env()
    allowed = {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT"}
    assert {k for k in env if not k.startswith("GIT_") and k not in ("PAGER", "SSH_ASKPASS")} <= allowed
    for secret in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "HERMES_HOME"):
        assert secret not in env
    assert env["PATH"] == "/usr/bin:/bin" and env["HOME"] == "/tmp/home" and env["LC_ALL"] == "C"
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "GIT_DIR" not in env


def test_git_env_survives_missing_path(monkeypatch):
    monkeypatch.delenv("PATH", raising=False)
    assert verify.git_env()["PATH"]  # a safe default so git can still be found


def test_run_git_still_works(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    r = verify.run_git(str(tmp_path), ["rev-parse", "--is-inside-work-tree"])
    assert r is not None and r[0] == 0 and r[1].strip() == "true"


def _hostile_repo(tmp_path):
    """A repo whose own .git/config asks git to run a program whenever it shows a signed commit, with a commit that
    claims a signature. Returns (repo, sha, marker the program writes)."""
    import subprocess
    repo, marker, prog = tmp_path / "repo", tmp_path / "ran", tmp_path / "prog.sh"
    env = {**verify.git_env(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}

    def git(*a, stdin=None):
        return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True, env=env,
                              input=stdin).stdout.strip()
    repo.mkdir()
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    head, _, body = git("cat-file", "commit", "HEAD").partition("\n\n")
    signed = f"{head}\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n iQ==\n -----END PGP SIGNATURE-----\n\n{body}\n"
    sha = git("hash-object", "-t", "commit", "-w", "--stdin", stdin=signed)
    git("reset", "-q", "--hard", sha)
    prog.write_text(f"#!/bin/sh\necho ran >> '{marker}'\nexit 1\n")
    prog.chmod(0o755)
    git("config", "log.showSignature", "true")
    for key in ("gpg.program", "gpg.openpgp.program", "gpg.ssh.program", "gpg.x509.program"):
        git("config", key, str(prog))
    return repo, sha, marker


def test_repo_config_cannot_run_a_program_when_a_commit_is_rechecked(tmp_path):
    import time
    repo, sha, marker = _hostile_repo(tmp_path)
    session = {"start": time.time() - 600, "calls": []}
    got = verify.recheck({"kind": "sha", "text": "x", "verdict": "no_receipt", "claim": {"kind": "sha", "sha": sha[:12]}},
                         str(repo), session=session)
    assert not marker.exists(), "git ran the repo's gpg.program"
    assert got and "made after the session started" in got[1]  # the commit time is still read


@pytest.mark.parametrize("fmt", ["openpgp", "ssh", "x509"])
def test_repo_config_cannot_run_a_program_when_a_format_asks_for_the_signature(tmp_path, fmt):
    import subprocess
    repo, sha, marker = _hostile_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "gpg.format", fmt], check=True, env=verify.git_env())
    verify.run_git(str(repo), ["show", "-s", "--format=%G?", sha])
    assert not marker.exists(), f"git ran the repo's {fmt} signature program"
