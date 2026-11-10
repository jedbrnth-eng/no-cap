"""Round 3: the bridge redacts again at the sink and never makes the known >40 KB window-edge limit worse.

docs/GUIDE.md "Known limits": a secret across a window edge of a tool output over 40 KB may reach a receipt in part.
The bridge exports receipt fields to a vault, so (1) every exported field goes through redact() again at the sink,
even when the stored record holds a raw secret (an upstream miss, an old store, a hand-edited store), and (2) the
vault never holds a character run of the secret that the local receipt store does not already hold.
Made-up vaults under tmp_path; synthetic secrets only.
"""
from pathlib import Path

from nocap import obsidian as O
from nocap.engine import Engine
from nocap.evidence import HEAD, TAIL, redact

GHP = "ghp_" + "Ab12" * 9  # synthetic GitHub-token shape
SK = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"  # synthetic


def cfg_for(vault, **extra):
    return {"obsidian_vault": str(vault), "obsidian_board": "on", "obsidian_learn": True, **extra}


def vault_text(v: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(v.rglob("*.md")))


def raw_record(claim, quote, profile="alpha"):
    """A stored record whose fields were NOT redacted (simulates an upstream miss)."""
    return {"type": "reply", "profile": profile, "session_id": "s1", "turn_id": "t1", "ts": 1_762_000_000,
            "receipts": [{"kind": "tests", "verdict": "CAP", "text": claim, "quote": quote,
                          "claim": {"kind": "tests", "frag": claim}}]}


def test_sink_redacts_a_raw_secret_in_a_stored_record_on_sync(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / ".agentbox.json").write_text("{}", encoding="utf-8")
    cfg = cfg_for(v)
    b = O.Bridge(lambda: tmp_path / "data", lambda k, d=None: cfg.get(k, d), lambda: "alpha")
    got = b.sync([raw_record(f"All tests pass, key {SK}.", f"3 failed, 41 passed token={GHP}")])
    assert got["written"] == 1
    text = vault_text(v)
    assert text  # not vacuous: a note and a board entry exist
    assert SK not in text and GHP not in text
    for s in (SK, GHP):  # no 12-char run of either secret survives anywhere in the vault
        assert not any(s[i:i + 12] in text for i in range(len(s) - 11)), s


def test_sink_field_is_redact_idempotent_and_bounded():
    for s in (f"x {SK} y", f"password={GHP}", "A" * 5000 + GHP):
        out = O.field(s)
        assert len(out) <= O.MAX_FIELD
        assert GHP not in out and SK not in out
        assert redact(out) == out


def test_window_edge_secret_is_no_worse_in_the_vault_than_in_the_store(tmp_path):
    """A >40 KB output with a secret straddling the HEAD edge, on a summary line. Whatever part of it the receipt
    store kept, the vault holds no run of the secret that the store does not also hold."""
    v = tmp_path / "vault"
    v.mkdir()
    cfg = cfg_for(v, obsidian_board="off")
    data = tmp_path / "data"
    e = Engine(lambda: data, lambda k, d=None: cfg.get(k, d))
    e.profile = lambda: "alpha"
    secret = "Zq9" * 30  # synthetic, 90 chars
    for cut in (5, 30, 60):
        filler = "x" * (HEAD - cut) + secret + " 3 failed, 41 passed in 0.02s\n"
        out = filler + ("." * 79 + "\n") * ((TAIL // 80) + 200) + "3 failed, 41 passed in 0.02s\n"
        assert len(out) > HEAD + TAIL
        e.on_tool(tool_name="terminal", args={"command": "pytest -q"}, result={"output": out, "exit_code": 1},
                  session_id=f"s{cut}", turn_id="t")
        e.on_reply(response_text="All tests pass.", session_id=f"s{cut}", turn_id="t", platform="cli")
    vtext = vault_text(v)
    assert vtext  # the 🧢 was exported
    store = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in data.rglob("*.jsonl"))
    for n in range(8, len(secret) + 1):
        for i in range(0, len(secret) - n + 1, 3):
            run = secret[i:i + n]
            if run in vtext:
                assert run in store, (n, i)
