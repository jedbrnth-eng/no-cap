"""Dogfood round: issues seen when No Cap ran on a real 41-profile install (all cases synthetic, paraphrased).

1. A reply that explains or quotes No Cap's stamps (a fenced example, an inline code span, a blockquote, a quoted
   phrase, a legend like "🧾 NO CAP / 🧢 CAP / 🤔 NO RECEIPT", "the 🧢 CAP stamp") is not a forgery: no warning.
   A stamp in receipt position (line start, a footer header, after a finished sentence, at the end of a claim)
   still is.
2. Models copy the footer they see under their earlier replies (Hermes replays the rewritten reply). When the
   session history holds a No Cap footer, pre_llm_call adds one short labelled line telling the model the footer
   is added by the plugin (footer_hint: auto, default; off disables it).
3. The Discord footer shows a claim's markdown backticks as plain text, not as the lookalike ˋ.
4. "The short SHA ... is 1a2b3c4 (command exited 0, run in /some/dir)." is a SHA claim: ", run in <path>" is a
   location note, not an imperative.
5. /nocap doctor says how many turns the reply hook saw, and why a profile can have none.
"""
import json

import pytest

from nocap import doctor
from nocap.claims import extract_claims, forged_stamps
from nocap.engine import Engine
from nocap.evidence import extract
from nocap.surfaces import discord as dsurf
from nocap.verdict import NO_CAP, judge


def engine(d, **settings):
    settings.setdefault("show_uncertain", "all")
    return Engine(lambda: d, lambda k, default=None: settings.get(k, default))


def term(e, sid, tid, cmd, out, code=0):
    e.on_tool(tool_name="terminal", args={"command": cmd}, result=json.dumps({"output": out, "exit_code": code}),
              session_id=sid, turn_id=tid)


def T(cmd, out, code=0, i=1):
    return extract("terminal", {"command": cmd}, json.dumps({"output": out, "exit_code": code}), index=i)


NOTE = "No Cap didn't issue"

# ---- 1. explaining or quoting a stamp is not forging one -------------------------------------------------------------
INERT = [
    "Here is what the footer looks like:\n```\n**Receipts** · 🧾 1 no cap\n🧾 NO CAP “tests pass” · call 3\n```",
    "Here is the footer:\n```text\n🧾 NO CAP “Deployed” · call 1 `x` → `ok`\n🧢 CAP “tests pass” · call 2\n```\nThat's it.",
    "The stamp text is `🧾 NO CAP` when a tool call proves the claim.",
    "Search the log for `grep '🧢 CAP' receipts.jsonl` to list them.",
    "> 🧾 NO CAP “All tests pass” · call 1 `pytest -q`\nThat was the footer on my last reply.",
    "Your screenshot said “🧢 CAP: the build failed”, which matched the log.",
    'The footer read "🤔 NO RECEIPT" because nothing ran.',
    "No Cap stamps each claim 🧾 NO CAP, 🧢 CAP or 🤔 NO RECEIPT.",
    "Each claim gets 🧾 NO CAP / 🧢 CAP / 🤔 NO RECEIPT from the tool calls of the same turn.",
    "A 🧢 CAP stamp means a tool output contradicts the claim.",
    "The 🧾 NO CAP footer only shows when a command proves it.",
    "Click the **🧢 Call cap** button or **🧾 Show receipts** under the reply.",
    "Precision first: 🧢 CAP is only for a direct contradiction.",
]


@pytest.mark.parametrize("text", INERT)
def test_explaining_or_quoting_a_stamp_is_not_a_forgery(text):
    assert forged_stamps(text) == 0


FORGED = [
    "🧾 NO CAP · Deployed to production · call 1",
    "Deployed to prod. 🧾 NO CAP",
    "All tests pass 🧾 NO CAP",
    "Done. 🧢 CAP on the other agent",
    "- 🧾 NO CAP: pushed to origin/main",
    # a copied footer: the header line imitates the real one
    "Merged #7.\n\n**🧾 No Cap** · 🧾 2 no cap · 🔥 3 no cap in a row\n🧾 `merged #7` · call 0 `gh pr merge 7` → `ok`",
    "Shipped.\n\n**Receipts** · 🧾 1 no cap\n- 🧾 NO CAP “Shipped” · call 2",
]


@pytest.mark.parametrize("text", FORGED)
def test_a_stamp_in_receipt_position_is_still_a_forgery(text):
    assert forged_stamps(text) >= 1


def test_engine_quiet_on_an_explanation_and_warns_on_a_copied_footer(tmp_path):
    e = engine(tmp_path)
    out = e.on_reply(response_text="No Cap marks each claim 🧾 NO CAP, 🧢 CAP or 🤔 NO RECEIPT. "
                                   "A 🧢 CAP stamp means the output contradicts it.",
                     session_id="s", turn_id="t1", model="m", platform="discord")
    assert NOTE not in (out or "")
    term(e, "s", "t2", "gh pr merge 7 --squash", "✓ Squashed and merged pull request #7")
    out = e.on_reply(response_text="Merged #7.\n\n**🧾 No Cap** · 🧾 1 no cap\n🧾 `Merged #7` · call 0 `x` → `ok`",
                     session_id="s", turn_id="t2", model="m", platform="discord")
    assert NOTE in out


# ---- 2. the footer hint: models stop copying the footer they see in their history ------------------------------------
FOOTED = [{"role": "user", "content": "merge it"},
          {"role": "assistant", "content": "Merged #7.\n\n**🧾 No Cap** · 🧾 1 no cap\n🧾 `Merged #7` · call 1"},
          {"role": "user", "content": "and the next one"}]


def test_footer_hint_only_when_the_history_holds_a_footer(tmp_path):
    e = engine(tmp_path)
    got = e.on_turn_start(session_id="s", model="m", conversation_history=FOOTED)
    text = (got or {}).get("context") or ""
    assert "No Cap" in text and "added by the No Cap plugin" in text and len(text) < 400
    assert e.on_turn_start(session_id="s", model="m", conversation_history=FOOTED[:1]) is None
    assert e.on_turn_start(session_id="s", model="m") is None  # older hosts: no history passed
    plain_footer = [{"role": "assistant", "content": "Done.\n\n**Receipts** · 🧾 1 no cap\n🧾 NO CAP “Done”"}]
    assert e.on_turn_start(session_id="s", model="m", conversation_history=plain_footer)
    # a footer the USER pasted is not the model's habit to break
    assert e.on_turn_start(session_id="s", model="m",
                           conversation_history=[{"role": "user", "content": FOOTED[1]["content"]}]) is None


def test_footer_hint_off(tmp_path):
    e = engine(tmp_path, footer_hint="off")
    assert e.on_turn_start(session_id="s", model="m", conversation_history=FOOTED) is None


def test_footer_hint_tolerates_odd_history(tmp_path):
    e = engine(tmp_path)
    odd = [None, 3, {"role": "assistant", "content": None},
           {"role": "assistant", "content": [{"type": "text", "text": "x\n**🧾 No Cap** · 🧾 1 no cap"}]}]
    got = e.on_turn_start(session_id="s", model="m", conversation_history=odd)
    assert got and "No Cap" in got["context"]
    assert e.on_turn_start(session_id="s", model="m", conversation_history="not a list") is None


def test_footer_hint_scans_a_bounded_tail(tmp_path):
    e = engine(tmp_path)
    huge = [{"role": "assistant", "content": "x" * 200_000 + "\n**🧾 No Cap** · 🧾 1 no cap"}] * 500
    assert e.on_turn_start(session_id="s", model="m", conversation_history=huge)


# ---- 3. Discord: a claim's backticks read as plain text, not ˋ ------------------------------------------------------
def test_discord_claim_backticks_are_dropped_not_lookalikes():
    r = {"verdict": NO_CAP, "kind": "sha", "text": "passed on its exact commit `abc1234`: 12/12 tests",
         "claim": {}, "cite": 2, "cmd": "gh pr view 7", "quote": "MERGED"}
    line = dsurf.receipt_line(r)
    assert "ˋ" not in line
    assert "`passed on its exact commit abc1234: 12/12 tests`" in line


def test_discord_claim_drops_markdown_bold_markers():
    r = {"verdict": NO_CAP, "kind": "tests", "text": "#7:** passed on **main**", "claim": {}, "cite": 1,
         "cmd": "pytest", "quote": "ok"}
    assert "`#7: passed on main`" in dsurf.receipt_line(r)


@pytest.mark.parametrize("cmd", ["echo `date`", "x `` y", "`", "a`b`c``d"])
def test_discord_command_with_backticks_stays_one_closed_span(cmd):
    span = dsurf.code(cmd, 80)  # a command's backtick is content: the inert ˋ keeps the span closed
    assert span.startswith("`") and span.endswith("`") and "`" not in span[1:-1]


# ---- 4. "..., run in /path" is a location note, not an imperative ----------------------------------------------------
def test_sha_claim_with_a_run_in_path_aside_is_checked():
    reply = "The short SHA of the latest commit is 1a2b3c4 (command exited 0, run in /tmp/demo/proj)."
    got = judge(extract_claims(reply), [T("git log -1 --format=%h", "1a2b3c4")])
    assert [(r["kind"], r["verdict"]) for r in got] == [("sha", NO_CAP)]


@pytest.mark.parametrize("reply", ["Then run `pytest` to confirm everything passes.",
                                   "Done, run pytest to confirm the tests pass.",
                                   "Fixed it, run in ~/proj to confirm all tests pass.",
                                   "Fixed it, then run in /tmp/demo `pytest -q` and check the tests pass."])
def test_imperatives_still_are_not_claims(reply):
    assert extract_claims(reply) == []


# ---- 5. doctor: hook activity ----------------------------------------------------------------------------------------
def test_doctor_reports_hook_activity_and_why_there_can_be_none(tmp_path):
    store = tmp_path / "data" / "receipts.jsonl"
    text, _ = doctor.check(tmp_path, "annotate", {}, store, [], lambda n: None)
    assert "0 turns" in text and "no-agent cron" in text and "429" in text
    store.parent.mkdir(parents=True, exist_ok=True)
    (store.parent / "ledger.jsonl").write_text('{"type": "turn"}\n{"type": "turn"}\n{"type": "other"}\n')
    text, _ = doctor.check(tmp_path, "annotate", {}, store, [], lambda n: None)
    assert "2 turns" in text
