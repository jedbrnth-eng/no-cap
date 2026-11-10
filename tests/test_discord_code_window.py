"""code() / claim_code() mask secrets in a window, not in the whole input.

Both keep at most `n` characters, so masking 100 KB to print 4,000 was wasted work: with the 0.2.1 CLI-password
rules the two calls together passed the 50 ms parser budget (tests/test_redos.py, discord_code). The window is the
kept part plus a margin longer than any bounded secret rule, so a secret that starts inside the kept part is still
masked whole.
"""
import pytest

from nocap.evidence import redact
from nocap.surfaces import discord
from nocap.surfaces.discord import _short, claim_code, code

PW = "hunter2" + "Pw"


def _old(s, n):
    s = _short(redact(str(s or "")), n).replace("`", "ˋ")
    return f"`{s}`" if s.strip() else ""


def test_long_input_is_not_masked_whole(monkeypatch):
    seen = []
    monkeypatch.setattr(discord, "redact", lambda s: (seen.append(len(s)), redact(s))[1])
    code("word " * 20_000, 4000)
    assert seen and max(seen) <= 4000 + discord._REDACT_MARGIN + 1


@pytest.mark.parametrize("n", [30, 45, 120, 4000])
@pytest.mark.parametrize("s", [
    "", "   ", "pytest -q", "sshpass -p " + PW + " ssh deploy@example.com",
    "DB_PASSWORD=" + PW + " make deploy", "a `b` c\n\nd" * 50, "word " * 3000, "x" * 9000,
    "ok\n" * 2000 + "GITHUB_TOKEN=" + "ghp_" + "a1B2" * 9,
])
def test_same_output_as_masking_everything(s, n):
    assert code(s, n) == _old(s, n)


@pytest.mark.parametrize("pad", [0, 3990, 3999, 4000, 4001])
def test_secret_across_the_cut_is_masked(pad):
    # the secret starts before, at or just after the cut and runs far past it
    s = "a" * pad + " DB_PASSWORD=" + PW + "Z9" * 30_000
    out = code(s, 4000)
    assert PW not in out and "Z9Z9Z9Z9" not in out


def test_secret_after_a_run_of_whitespace():
    # whitespace is collapsed before the cut, so the kept part can start far into the raw text
    s = "x" + " \n" * 40_000 + "sshpass -p " + PW + " ssh host"
    out = code(s, 4000)
    assert PW not in out and "sshpass -p [redacted]" in out


def test_unterminated_private_key_across_the_cut():
    body = "MIIEvQ" + "Ab3/" * 20_000
    out = code("key: -----BEGIN RSA PRIVATE KEY-----\n" + body, 200)
    assert "MIIEvQ" not in out and "Ab3/Ab3/" not in out


def test_claim_code_window():
    s = "**All tests pass** with token " + "ghp_" + "a1B2" * 9 + " " + "word " * 30_000
    assert "a1B2a1B2" not in claim_code(s, 4000)
    assert claim_code(s, 4000) == _old(" ".join(s.replace("**", "").split()), 4000)
