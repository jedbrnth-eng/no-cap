"""Secret masking before anything touches disk, the store's file modes, and what a reply record keeps.

Every secret below is synthetic (built by concatenation so no scanner mistakes it for a real one).
"""
import json
import os
import stat
from pathlib import Path

import pytest

from nocap.engine import Engine
from nocap.evidence import extract, redact, summary
from nocap.store import Store

R = "Q7wX2mK9pL4sT8vB1nZ6cR3yH5jD0fGa"  # 32 random-looking characters, not a real key
SHAPES = {  # name: (text, the part that must not survive)
    "openai sk-": ("sk-" + "proj-" + R, R),
    "anthropic sk-ant": ("sk-" + "ant-api03-" + R + R[:8], R),
    "github ghp_": ("ghp" + "_" + R[:36], R[:30]),
    "github_pat_": ("github" + "_pat_" + "11ABCDEFG0" + R + R[:20], R),
    "slack xoxb": ("xox" + "b-1234567890-1234567890123-" + R[:24], R[:24]),
    "aws access key id": ("AKIA" + "IOSFODNN7EXAMPLE", "IOSFODNN7EXAMPLE"),
    "aws secret key": ("wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY", "bPxRfiCYEXAMPLEKEY"),
    "google AIza": ("AIza" + "SyD" + R[:32], R[:32]),
    "huggingface hf_": ("hf" + "_" + "AbCdEfGhIjKlMnOpQrStUvWxYz12345678", "AbCdEfGhIjKlMnOpQrStUvWxYz12345678"),
    "stripe sk_live": ("sk" + "_live_" + R[:24], R[:24]),
    "jwt": ("eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
    "bearer header": ("Authorization: Bearer " + R[:20], R[:20]),
    "password in url": ("https://admin:" + "hunter2Pass" + "@db.internal.example/x", "hunter2Pass"),
    "postgres dsn": ("postgres://app:" + "S3cretPw" + "@10.0.0.5:5432/prod", "S3cretPw"),
    "pem private key": ("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ\n"
                        "-----END OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ"),
    "telegram bot token": ("1234567890:" + "AAH" + R[:32], R[:32]),
    "discord bot token": ("MTE" + "xNjQ0NTY3ODkwMTIzNDU2.GhIjKl." + R[:27], R[:27]),
    "export FOO_KEY=": ("export OPENROUTER_KEY=" + "or" + "-v1-" + R[:20], "or-v1-" + R[:20]),
    "short hex api key": ("api_key " + "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"),
    "npm token": ("npm" + "_" + R[:36], R[:30]),
}
ENV_PAIRS = {  # KEY=value pairs whose name says secret; the value must go, the name stays readable
    "DB_PASSWORD=hunter2 pytest -q": "hunter2",
    "GITHUB_TOKEN=abc123 gh pr create": "abc123",
    "MY_TOKEN=xyz12345": "xyz12345",
    "OPENROUTER_KEY=orv1abcdef": "orv1abcdef",
    "client_secret: shhh-value": "shhh-value",
    "DATADOG_API_KEY=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    'curl -H "X-Api-Key: k3y-v4lue" https://api.example.com': "k3y-v4lue",
    '{"password": "pa55word"}': "pa55word",
    "AWS_SECRET_ACCESS_KEY=abcdEFGH1234": "abcdEFGH1234",
    "SESSION_COOKIE=c00kie-v4l": "c00kie-v4l",
    "NODE_ENV=production": None,  # not a secret-named variable: stays
    "mysql --password=s3cr3t-pw db": "s3cr3t-pw",
}
CLI_PASSWORDS = {  # S9: passwords given as command-line flags; the user name and the rest of the command stay
    "curl -u admin:" + "hunter2Pw" + " https://api.example.com/x": ("hunter2Pw", "curl -u admin:[redacted] https"),
    "curl -sS --user admin:" + "hunter2Pw" + " https://api.example.com/x": ("hunter2Pw", "--user admin:[redacted]"),
    "curl --user=admin:" + "hunter2Pw" + " https://api.example.com/x": ("hunter2Pw", "--user=admin:[redacted]"),
    "mysql -u root -p" + "hunter2Pw" + " shop": ("hunter2Pw", "mysql -u root -p[redacted] shop"),
    "mysqldump -h db -p" + "hunter2Pw" + " shop > dump.sql": ("hunter2Pw", "-p[redacted] shop"),
    "sshpass -p " + "hunter2Pw" + " ssh deploy@example.com": ("hunter2Pw", "sshpass -p [redacted] ssh"),
    "sshpass -p" + "hunter2Pw" + " scp a example.com:b": ("hunter2Pw", "sshpass -p[redacted] scp"),
    "vault login --pass " + "hunter2Pw": ("hunter2Pw", "--pass [redacted]"),
    "tool --passphrase=" + "hunter2Pw" + " sign": ("hunter2Pw", "--passphrase=[redacted]"),
    "openssl pkcs12 --passwd " + "hunter2Pw": ("hunter2Pw", "--passwd [redacted]"),
    "redis-cli -h cache -a " + "hunter2Pw" + " ping": ("hunter2Pw", "-a [redacted] ping"),
}
KEEP = [  # ordinary evidence text that must come through unchanged
    "curl -u admin https://api.example.com/x",
    "mysql -u root -p shop",
    "ssh -p 2222 deploy@example.com",
    "pytest -p no:cacheprovider -q",
    "docker run -u 1000:1000 img",
    "the tests pass because of the fix",
    "3 failed, 41 passed in 0.12s",
    "git push origin feat/login",
    "[main 1a2b3c4] Fix the login check",
    "pytest -q tests/test_auth.py -k token_refresh",
    "https://example.com/docs/page",
    "Tests run: 48, Failures: 0, Errors: 0, Skipped: 0",
    "git commit -m 'rotate keys' && git push",
    "cargo test -p oxc_parser",
]


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_secret_shapes_are_masked(name):
    text, core = SHAPES[name]
    assert core not in redact("echo " + text)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_secret_shapes_never_reach_disk(name, tmp_path):
    text, core = SHAPES[name]
    st = Store(lambda: tmp_path, lambda: 30)
    ev = extract("terminal", {"command": "curl -H '" + text + "' x"}, {"output": text, "exit_code": 0})
    st.append({"type": "reply", "ts": 0, "session_id": "s", "turn_id": "t", "calls": [summary(ev)],
               "receipts": [{"claim": {"text": "deployed with " + text}, "quote": text}]})
    assert core not in (tmp_path / "receipts.jsonl").read_text()


@pytest.mark.parametrize("text", sorted(ENV_PAIRS))
def test_secret_named_assignments_are_masked(text):
    core = ENV_PAIRS[text]
    out = redact(text)
    if core is None:
        assert out == text
        return
    assert core not in out and "[redacted]" in out
    name = text.split("=")[0].split(":")[0].split()[-1].strip('{"')
    assert name in out  # the variable name stays, so the stored command is still readable


@pytest.mark.parametrize("text", KEEP)
def test_ordinary_evidence_is_not_masked(text):
    assert redact(text) == text


def test_store_file_and_dir_are_private(tmp_path):
    d = tmp_path / "plugin-data" / "no-cap"
    st = Store(lambda: d, lambda: 30)
    st.append({"type": "reply", "ts": 0, "session_id": "s", "turn_id": "t", "receipts": []})
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(d / "receipts.jsonl").st_mode) == 0o600


def test_store_tightens_an_existing_world_readable_file(tmp_path):
    d = tmp_path / "data"
    d.mkdir(mode=0o755)
    (d / "receipts.jsonl").write_text("")
    os.chmod(d / "receipts.jsonl", 0o644)
    Store(lambda: d, lambda: 30).append({"type": "reply", "ts": 1e12, "session_id": "s", "receipts": []})
    assert stat.S_IMODE(os.stat(d / "receipts.jsonl").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700


def test_prune_rewrite_keeps_mode_0600(tmp_path):
    st = Store(lambda: tmp_path, lambda: 30)
    st.append({"type": "reply", "ts": 0, "session_id": "old", "receipts": []})  # pruned on the next first append
    st2 = Store(lambda: tmp_path, lambda: 30)
    st2.append({"type": "reply", "ts": 1e12, "session_id": "new", "receipts": []})
    assert stat.S_IMODE(os.stat(tmp_path / "receipts.jsonl").st_mode) == 0o600
    assert not (tmp_path / "receipts.tmp").exists()


def test_reply_record_keeps_only_cited_calls_plus_a_digest(tmp_path):
    e = Engine(lambda: tmp_path, lambda k, v=None: v)
    for c in ["cat ~/notes/diary.md", "ls ~/clients/acme", "pytest -q"]:
        e.on_tool(tool_name="terminal", args={"command": c}, result={"output": "3 passed in 0.1s", "exit_code": 0},
                  session_id="s", turn_id="t")
    e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m")
    raw = (tmp_path / "receipts.jsonl").read_text()
    rec = json.loads(raw.splitlines()[-1])
    assert [c["cmd"] for c in rec["calls"]] == ["pytest -q"]
    assert rec["ledger"]["n"] == 3 and rec["ledger"]["digest"].startswith("sha256:")
    assert "diary" not in raw and "acme" not in raw


def test_ledger_digest_changes_with_the_calls(tmp_path):
    def run(cmds):
        e = Engine(lambda: tmp_path / str(len(cmds)), lambda k, v=None: v)
        for c in cmds:
            e.on_tool(tool_name="terminal", args={"command": c}, result={"output": "1 passed", "exit_code": 0},
                      session_id="s", turn_id="t")
        e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m")
        return json.loads((tmp_path / str(len(cmds)) / "receipts.jsonl").read_text().splitlines()[-1])["ledger"]
    assert run(["ls", "pytest"])["digest"] != run(["ls a", "ls b", "pytest"])["digest"]


@pytest.mark.parametrize("text", sorted(CLI_PASSWORDS))
def test_command_line_passwords_are_masked(text):
    core, keep = CLI_PASSWORDS[text]
    out = redact(text)
    assert core not in out and keep in out, out


@pytest.mark.parametrize("text", sorted(CLI_PASSWORDS))
def test_command_line_passwords_never_reach_disk(text, tmp_path):
    e = Engine(lambda: tmp_path, lambda k, v=None: v)
    e.on_tool(tool_name="terminal", args={"command": text}, result={"output": "ok", "exit_code": 0}, session_id="s",
              turn_id="t")
    e.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result={"output": "3 passed in 0.1s", "exit_code": 0},
              session_id="s", turn_id="t")
    e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m")
    for f in tmp_path.iterdir():
        assert CLI_PASSWORDS[text][0] not in f.read_text(), f.name


def test_home_dir_becomes_tilde_in_stored_cmd_and_workdir(tmp_path, monkeypatch):
    """S9: the user's home path never lands in a stored or printed command or working dir (it names the user)."""
    home = "/Users/" + "alice-example"
    monkeypatch.setenv("HOME", home)
    ev = extract("terminal", {"command": f"cd {home}/proj && pytest -q", "workdir": f"{home}/proj"},
                 {"output": "3 passed in 0.1s", "exit_code": 0})
    assert ev["cmd"] == "cd ~/proj && pytest -q" and ev["workdir"] == "~/proj" and ev["where"] == "~/proj"
    ev = extract("terminal", {"command": f"ls {home}x/y"}, {"output": "", "exit_code": 0})
    assert ev["cmd"] == f"ls {home}x/y"  # only the home dir itself, not a longer name that starts the same
    e = Engine(lambda: tmp_path / "d", lambda k, v=None: v)
    e.on_tool(tool_name="terminal", args={"command": f"cd {home}/proj && pytest -q", "workdir": f"{home}/proj"},
              result={"output": "3 passed in 0.1s", "exit_code": 0}, session_id="s", turn_id="t")
    e.on_reply(response_text="All tests pass.", session_id="s", turn_id="t", model="m")
    assert "alice-example" not in "".join(f.read_text() for f in (tmp_path / "d").iterdir())
    assert "alice-example" not in e.nocap("", session_id="s")
