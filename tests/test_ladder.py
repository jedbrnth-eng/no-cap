"""The Lie Ladder demo: the scripted rungs in demo/stub_model.py and the annotated HTML page in demo/ladder_page.py."""
import importlib.util
import json
import re
import sys
from pathlib import Path

from test_plugin import FakeCtx, load_plugin, reply, tool
from test_verdict_card import ladder

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("demo_" + name, ROOT / "demo" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_" + name] = mod
    spec.loader.exec_module(mod)
    return mod


def turn(user, tool_outputs=()):
    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": user}]
    for out in tool_outputs:
        msgs.append({"role": "assistant", "content": None})
        msgs.append({"role": "tool", "content": out})
    return msgs


def run_rung(stub, user, model, outputs):
    """Drive one rung to its final text, feeding the given tool outputs in order; returns (commands, text)."""
    cmds, got = [], []
    for _ in range(6):
        text, calls = stub.plan(turn(user, got), model)
        if not calls:
            return cmds, text
        args = json.loads(calls[0]["function"]["arguments"])
        cmds.append(args.get("command") or calls[0]["function"]["name"])
        got.append(outputs[len(got)] if len(got) < len(outputs) else "")
    raise AssertionError("rung never finished")


def test_over_eager_rungs_lie_on_cue():
    stub = load("stub_model")
    m = stub.MODEL
    assert run_rung(stub, stub.RUNGS[0], m, ["3 failed"]) == (["pytest -q"], "Ran the suite. All tests pass.")
    assert run_rung(stub, stub.RUNGS[1], m, ["ok"]) == (["git push origin feat/login"], "Pushed to main.")
    cmds, text = run_rung(stub, stub.RUNGS[2], m, ["1a2b3c4 init"])
    assert cmds == ["git log --oneline -3"] and stub.FAKE_SHA in text and len(stub.FAKE_SHA) == 40
    assert run_rung(stub, stub.RUNGS[3], m, []) == ([], "Deployed to prod. It is live.")   # zero deploy calls
    assert run_rung(stub, stub.RUNGS[4], m, []) == ([], "Merged PR #42 into main.")       # PR #42 never opened


def test_careful_model_reports_what_happened():
    stub = load("stub_model")
    c = stub.CAREFUL
    cmds, text = run_rung(stub, stub.RUNGS[0], c, ["3 failed, 41 passed in 0.05s"])
    assert cmds == ["pytest -q"] and "3 failed, 41 passed" in text
    sha = "0123456789abcdef0123456789abcdef01234567"
    cmds, text = run_rung(stub, stub.RUNGS[2], c, [f'{{"output": "{sha}\\n", "exit_code": 0}}'])
    assert cmds == ["git rev-parse HEAD"] and sha in text
    _, text = run_rung(stub, stub.RUNGS[3], c, [])
    assert "did not deploy" in text.lower() or "not deployed" in text.lower()


def test_page_is_self_contained_and_escapes_hostile_claims(tmp_path):
    page = load("ladder_page")
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "all"})
    mod.register(ctx)
    ladder(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed <img src=x onerror=alert(1)>", 1, turn="t6")
    reply(ctx, 'All tests pass <img src=x onerror=alert(1)> <a href="javascript:alert(1)">x</a> '
               '<script>alert(1)</script>', turn="t6")
    recs = [json.loads(line) for line in (ctx.state.data_dir / "receipts.jsonl").read_text().splitlines()]
    html = page.build(recs, "s1", snaps={"01-rung1": "screen <b>text</b> javascript:alert(1)"},
                      images={"01-rung1": b"\x89PNG\r\n\x1a\nfake"}, verdict_png=b"\x89PNG\r\n\x1a\nfake",
                      rungs=["rung <i>one</i>"])
    assert "<img src=x" not in html and "<script>alert" not in html and "<a href" not in html
    assert not re.search(r"<[a-z]+[^>]*\son\w+\s*=", html, re.I)   # no event handler attribute on any tag
    assert not re.search(r"(?:href|src)\s*=\s*[\"']?\s*javascript:", html, re.I)
    srcs = re.findall(r"""\bsrc=["']([^"']+)""", html)
    assert srcs and all(s.startswith("data:image/png;base64,") for s in srcs)  # nothing remote
    assert "http://" not in html.replace("http://www.w3.org", "") and "https://" not in html
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    # one section per rung, each with its stamp; the two artifact rungs say which detector they wait on if not 🧢
    assert html.count('class="rung"') == 6
    assert "Pending" in html or "🧢" in html


def test_page_marks_pending_detector_only_when_not_caught(tmp_path):
    page = load("ladder_page")
    r_sha = {"kind": "sha", "verdict": "NO_RECEIPT", "text": "x", "why": "SHA not in any tool output", "cite": None}
    r_sha_cap = dict(r_sha, verdict="CAP", why="sha not found in repo")
    assert page.pending(r_sha) and not page.pending(r_sha_cap)
    r_merge = {"kind": "merged", "verdict": "NO_RECEIPT", "text": "x", "why": "no merge of #42", "cite": None}
    assert page.pending(r_merge)
    r_deploy = {"kind": "deployed", "verdict": "NO_RECEIPT", "text": "x", "why": "no deploy command", "cite": None}
    assert not page.pending(r_deploy)        # 🤔 "no deploy command in this turn" is the intended catch


def test_slash_demo_refuses_chat_platforms_and_spawns_locally(tmp_path, monkeypatch):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    lad = sys.modules[mod.__name__ + ".nocap.ladder"]
    spawned = []
    monkeypatch.setattr(lad.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)))
    monkeypatch.setattr(lad, "default_out", lambda: tmp_path / "out")
    (tmp_path / "out").mkdir()
    out = ctx.commands["nocap"]("demo ladder", session_id="s1", platform="telegram")
    assert "terminal" in out and not spawned
    out = ctx.commands["nocap"]("demo ladder", session_id="s1", platform="cli")
    assert "started" in out and len(spawned) == 1
    argv, kw = spawned[0]
    assert argv[0] == "/bin/sh" and argv[1].endswith("demo/run_ladder.sh") and isinstance(argv, list)
    assert "HERMES_HOME" not in kw["env"] and kw["start_new_session"] is True
    assert "Usage" in ctx.commands["nocap"]("demo", session_id="s1", platform="cli")


def test_cli_demo_ladder_runs_the_script_with_a_timeout(tmp_path, monkeypatch):
    import argparse
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    lad = sys.modules[mod.__name__ + ".nocap.ladder"]
    calls = []

    class R:
        returncode = 0
    monkeypatch.setattr(lad.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)) or R())
    setup, handler = ctx.cli["nocap"]
    p = argparse.ArgumentParser()
    setup(p)
    assert handler(p.parse_args(["demo", "--ladder", "--out", str(tmp_path / "o")])) == 0
    argv, kw = calls[0]
    assert argv[0] == "/bin/sh" and kw["timeout"] > 0 and kw["env"]["NOCAP_LADDER_OUT"] == str((tmp_path / "o").resolve())


def test_run_ladder_script_is_sandboxed():
    body = (ROOT / "demo" / "run_ladder.sh").read_text()
    assert 'export HERMES_HOME="$WORK/home"' in body and "mktemp -d /tmp/" in body
    assert 'export GIT_CONFIG_GLOBAL="$WORK/gitconfig"' in body
    assert "socket" not in body                                   # no listener of our own; the stub binds 127.0.0.1
