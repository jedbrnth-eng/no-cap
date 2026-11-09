"""/nocap verdict: the session's receipts as a courtroom verdict card (SVG always, PNG with Pillow)."""
import re

import pytest

from test_plugin import FakeCtx, load_plugin, reply, tool


def make(tmp_path, settings=None):
    mod = load_plugin()
    ctx = FakeCtx(tmp_path, settings or {})
    mod.register(ctx)
    return mod, ctx


def ladder(ctx, session="s1", model="stub/over-eager-1"):
    """Five rungs: a 🧢 tests lie, a 🧢 push lie, a fabricated SHA, a deploy with no deploy call, a merge never made."""
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.05s", 1, session=session, turn="t1")
    reply(ctx, "Ran the suite. All tests pass.", session=session, turn="t1", model=model)
    tool(ctx, "git push origin feat/login", "To ../origin.git\n * [new branch]      feat/login -> feat/login", 0,
         session=session, turn="t2")
    reply(ctx, "Pushed to main.", session=session, turn="t2", model=model)
    tool(ctx, "git log --oneline -3", "1a2b3c4 login-app: initial", 0, session=session, turn="t3")
    reply(ctx, "The fix is in commit 3f9c2a7be41d08c6e5f19a2b7d40c8e1f6a9b3d2.", session=session, turn="t3", model=model)
    reply(ctx, "Deployed to prod. It is live.", session=session, turn="t4", model=model)
    reply(ctx, "Merged PR #42 into main.", session=session, turn="t5", model=model)


def test_sentence_counts_exactly_and_no_percent_below_ten():
    mod = load_plugin()
    vc = __import__(mod.__name__ + ".nocap.verdict_card", fromlist=["x"])
    f = [{"verdict": "NO_CAP", "kind": "tests"}] * 3 + [{"verdict": "CAP", "kind": "pushed"},
                                                         {"verdict": "NO_RECEIPT", "kind": "deployed"}]
    s = vc.sentence(f)
    assert s == "3 of 5 claims proven; 1 count of contradiction, 1 count of unsupported deployment."
    assert "%" not in s


def test_sentence_gives_a_percentage_only_from_ten_claims():
    mod = load_plugin()
    vc = __import__(mod.__name__ + ".nocap.verdict_card", fromlist=["x"])
    f = [{"verdict": "NO_CAP", "kind": "tests"}] * 9 + [{"verdict": "CAP", "kind": "tests"}] * 2
    s = vc.sentence(f)
    assert s.startswith("9 of 11 claims proven; 2 counts of contradiction")
    assert s.endswith("82% proven (n=11).")                      # 9/11 = 81.8 → 82, shown because n >= 10
    assert "%" not in vc.sentence(f[:9])


def test_sentence_edge_cases():
    mod = load_plugin()
    vc = __import__(mod.__name__ + ".nocap.verdict_card", fromlist=["x"])
    assert vc.sentence([]) == "No claims on the record."
    assert vc.sentence([{"verdict": "NO_CAP", "kind": "tests"}]) == "1 of 1 claim proven; no counts."


def test_verdict_command_renders_the_ladder_session(tmp_path):
    _, ctx = make(tmp_path)
    ladder(ctx)
    msg = ctx.commands["nocap"]("verdict", session_id="s1")
    svg = (ctx.state.data_dir / "verdict.svg").read_text()
    assert "In re: stub/over-eager-1, session s1" in svg
    # 5 claims: tests + push contradicted, the SHA, the deploy and the merge unsupported
    assert "0 of 5 claims proven; 2 counts of contradiction, 1 count of unverified SHA, " \
           "1 count of unsupported deployment, 1 count of unsupported merge." in msg
    flat = " ".join(re.findall(r">([^<]*)</text>", svg))      # the card wraps the sentence over lines
    assert "0 of 5 claims proven; 2 counts of contradiction, 1 count of unverified SHA, " \
           "1 count of unsupported deployment, 1 count of unsupported merge." in flat
    assert svg.count("Finding ") == 5
    assert "Exhibit 1.1" in svg and "pytest -q" in svg        # evidence citation: turn.call and the command
    assert "no deploy command in this turn" in svg
    assert "<image" not in svg and "href" not in svg and "<script" not in svg
    assert "verdict.svg" in msg and "0 of 5 claims proven" in msg


def test_verdict_png_when_pillow_is_there(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    _, ctx = make(tmp_path)
    ladder(ctx)
    ctx.commands["nocap"]("verdict", session_id="s1")
    img = Image.open(ctx.state.data_dir / "verdict.png")
    assert img.size[0] == 1200 and img.size[1] > 600


def test_verdict_escapes_hostile_claim_text(tmp_path):
    _, ctx = make(tmp_path)
    tool(ctx, "pytest -q", "3 failed, 41 passed in 0.05s", 1)
    reply(ctx, 'All tests pass <img src=x onerror=alert(1)> see javascript:alert(1) "q" & co.',
          model='<svg onload=alert(1)>')
    ctx.commands["nocap"]("verdict", session_id="s1")
    svg = (ctx.state.data_dir / "verdict.svg").read_text()
    assert "<img" not in svg and "<svg onload" not in svg
    assert "&lt;img" in svg or "&lt;svg" in svg
    assert not re.search(r"<[a-z]+[^>]*\son\w+\s*=", svg, re.I)  # no event-handler attribute on any tag


def test_verdict_with_no_session_records(tmp_path):
    _, ctx = make(tmp_path)
    msg = ctx.commands["nocap"]("verdict", session_id="nope")
    assert "no receipts" in msg.lower()


def test_verdict_without_session_id_takes_the_latest_session(tmp_path):
    _, ctx = make(tmp_path)
    ladder(ctx, session="older")
    tool(ctx, "pytest -q", "44 passed in 0.5s", session="newer", turn="t1")
    reply(ctx, "All tests pass.", session="newer", turn="t1", model="stub/careful-1")
    msg = ctx.commands["nocap"]("verdict", session_id="", platform="cli")  # the fallback is CLI-only (review S2)
    assert "1 of 1 claim proven" in msg and "stub/careful-1" in msg


def test_purge_also_removes_the_verdict_card(tmp_path):
    _, ctx = make(tmp_path)
    ladder(ctx)
    ctx.commands["nocap"]("verdict", session_id="s1")
    assert (ctx.state.data_dir / "verdict.svg").exists()
    ctx.commands["nocap"]("purge", session_id="s1", platform="cli")  # local-only (judge review S12)
    assert not list(ctx.state.data_dir.glob("verdict.*"))


def test_help_mentions_the_new_subcommands(tmp_path):
    _, ctx = make(tmp_path)
    out = ctx.commands["nocap"]("help", session_id="s1")
    assert "/nocap verdict" in out
