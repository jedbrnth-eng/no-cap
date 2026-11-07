"""The git child gets a minimal environment, never the agent's provider keys (catalog review, PR #149272)."""
import os

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
