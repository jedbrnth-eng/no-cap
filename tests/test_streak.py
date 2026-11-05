"""The 🔥 "no cap in a row" streak counts only replies whose shown receipts are all 🧾. A 🧢 resets it; a reply
with a 🤔 (no receipt) neither extends nor resets it."""
import time

from nocap import board, desktop, score


def rec(*verdicts, hidden=(), session="s1"):
    receipts = [{"verdict": v, "kind": "tests"} for v in verdicts]
    receipts += [{"verdict": v, "kind": "tests", "hidden": True} for v in hidden]
    return {"type": "reply", "ts": time.time(), "session_id": session, "model": "m", "receipts": receipts}


def streaks(records):
    slim = [board._slim(r) for r in records]
    return (score.streak(records), desktop.session_view(records, "s1")["streak"],
            board._row("a", slim, time.time(), 1)["streak"])


def test_only_unsure_replies_do_not_extend_the_streak():
    recs = [rec("NO_CAP"), rec("NO_CAP"), rec("NO_RECEIPT"), rec("NO_RECEIPT"), rec("NO_RECEIPT")]
    assert streaks(recs) == (2, 2, 2)


def test_a_mixed_reply_does_not_count():
    assert streaks([rec("NO_CAP"), rec("NO_CAP", "NO_RECEIPT")]) == (1, 1, 1)


def test_all_proven_replies_count_and_a_cap_resets():
    recs = [rec("NO_CAP"), rec("CAP"), rec("NO_CAP"), rec("NO_CAP", "NO_CAP"), rec("NO_RECEIPT"), rec("NO_CAP")]
    assert streaks(recs) == (3, 3, 3)
    assert streaks(recs + [rec("CAP", "NO_CAP")]) == (0, 0, 0)


def test_hidden_unsure_receipts_do_not_spoil_a_proven_reply():
    assert streaks([rec("NO_CAP", hidden=("NO_RECEIPT",)), rec("NO_CAP")]) == (2, 2, 2)


def test_a_reply_with_only_hidden_receipts_does_not_count():
    assert streaks([rec("NO_CAP"), rec(hidden=("NO_RECEIPT",))]) == (1, 1, 1)
