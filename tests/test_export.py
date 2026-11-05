"""`hermes nocap export --json|--csv` and `hermes nocap metrics --file`: redacted, file-only, no listener."""
import argparse
import csv
import io
import json
import os
import stat

import pytest

from test_plugin import FakeCtx, load_plugin, reply, tool

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # fake token shape (split so scanners don't flag the source)


def make(tmp_path):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, {"show_uncertain": "all"})
    mod.register(ctx)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.05s", 1)
    reply(ctx, "All tests pass.", model="model/a")
    tool(ctx, f"git push https://x:{SECRET}@example.com/r.git feat/login", " * [new branch] feat/login -> feat/login",
         0, turn="t2")
    reply(ctx, "Pushed to feat/login.", turn="t2", model='model/"b"\n')
    reply(ctx, "=HYPERLINK(\"http://evil.example\") Deployed to prod.", turn="t3", model="model/a")
    return mod, ctx


def run(ctx, argv):
    setup, handler = ctx.cli["nocap"]
    p = argparse.ArgumentParser()
    setup(p)
    return handler(p.parse_args(argv))


def ex():
    mod = load_plugin()
    return __import__(mod.__name__ + ".nocap.export", fromlist=["x"])


def test_json_export(tmp_path, capsys):
    _, ctx = make(tmp_path)
    run(ctx, ["export", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["format"] == "no-cap-receipts/1"
    verdicts = [r["verdict"] for r in data["receipts"]]
    assert verdicts.count("CAP") == 1 and verdicts.count("NO_CAP") == 1 and "NO_RECEIPT" in verdicts
    assert SECRET not in json.dumps(data)


def test_ids_stay_joinable(tmp_path, capsys):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path)
    mod.register(ctx)
    sid = "local-e212a393ed7e15cd822982f8f3fe44ab81a5d9c341dc462e7f347934dd078411"
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.05s", 1, session=sid, turn=sid + ":1:ab")
    reply(ctx, "All tests pass.", session=sid, turn=sid + ":1:ab")
    run(ctx, ["export", "--json"])
    r = json.loads(capsys.readouterr().out)["receipts"][0]
    assert r["session_id"] == sid and r["turn_id"] == sid + ":1:ab"


def test_csv_export_guards_formulas_and_redacts(tmp_path, capsys):
    _, ctx = make(tmp_path)
    run(ctx, ["export", "--csv"])
    text = capsys.readouterr().out
    rows = list(csv.DictReader(io.StringIO(text)))
    assert {"ts", "session_id", "model", "kind", "verdict", "claim", "evidence"} <= set(rows[0])
    assert SECRET not in text
    claims = [r["claim"] for r in rows]
    assert not any(c.startswith(("=", "+", "-", "@")) for c in claims)
    assert any(c.startswith("'=HYPERLINK") for c in claims)


def test_export_to_a_private_file(tmp_path, capsys):
    _, ctx = make(tmp_path)
    out = tmp_path / "out" / "r.json"
    run(ctx, ["export", "--json", "--out", str(out)])
    assert json.loads(out.read_text())["receipts"]
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600


def test_metrics_file_is_prometheus_text(tmp_path, capsys):
    _, ctx = make(tmp_path)
    path = tmp_path / "nocap.prom"
    run(ctx, ["metrics", "--file", str(path)])
    text = path.read_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert "# TYPE nocap_claims_total counter" in text
    assert 'nocap_claims_total{model="model/a",kind="tests",verdict="CAP"} 1' in text
    assert 'model="model/\\"b\\""' in text                   # quotes escaped per the exposition format, newline folded
    assert "\n\"" not in text
    assert "# TYPE nocap_cap_rate gauge" in text
    for line in text.splitlines():
        assert line.startswith("#") or line.split()[-1].replace(".", "", 1).isdigit()
    assert SECRET not in text


def test_metrics_requires_a_file_and_never_listens(tmp_path):
    _, ctx = make(tmp_path)
    with pytest.raises(SystemExit):
        run(ctx, ["metrics"])
    src = (ex().__file__)
    body = open(src).read()
    assert "socket" not in body and "http.server" not in body and "serve" not in body


def test_metrics_refuses_a_directory(tmp_path, capsys):
    _, ctx = make(tmp_path)
    rc = run(ctx, ["metrics", "--file", str(tmp_path)])
    assert rc == 1


def test_export_redacts_even_unscrubbed_store_lines(tmp_path):
    """A store line written before redaction existed (or by hand) still leaves export redacted."""
    m = ex()
    rec = {"type": "reply", "session_id": "s", "model": "m", "ts": 1,
           "receipts": [{"kind": "tests", "verdict": "CAP", "text": f"token {SECRET}", "cmd": f"echo {SECRET}",
                         "quote": SECRET, "why": "", "cite": 1, "tool": "terminal"}]}
    assert SECRET not in m.to_json([rec]) and SECRET not in m.to_csv([rec]) and SECRET not in m.metrics([rec])
