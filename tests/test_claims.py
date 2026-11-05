from nocap.claims import extract_claims


def kinds(text):
    return [c["kind"] for c in extract_claims(text)]


def one(text, kind):
    found = [c for c in extract_claims(text) if c["kind"] == kind]
    assert len(found) == 1, (text, extract_claims(text))
    return found[0]


def test_all_tests_pass_is_a_claim():
    c = one("Done. All tests pass.", "tests")
    assert c["all_pass"] is True


def test_counted_pass_claim():
    c = one("41 passed, 0 failed.", "tests")
    assert c["passed"] == 41
    assert c["failed"] == 0


def test_slash_count():
    c = one("Tests: 12/12 passing on main.", "tests")
    assert c["passed"] == 12


def test_failure_count_claim():
    c = one("3 tests failed, the rest are green.", "tests")
    assert c["failed"] == 3


def test_hedged_tests_are_not_claims():
    assert "tests" not in kinds("The tests should pass now.")
    assert "tests" not in kinds("Once you run it, all tests will pass.")
    assert "tests" not in kinds("Do the tests pass?")
    assert "tests" not in kinds("If the tests pass, merge it.")


def test_future_push_is_not_a_claim():
    assert kinds("I will push the branch next.") == []
    assert kinds("I'll push after review.") == []
    assert kinds("Next step: push to origin.") == []


def test_negated_push_is_not_a_claim():
    assert "pushed" not in kinds("I have not pushed anything.")
    assert "pushed" not in kinds("Nothing was pushed.")


def test_pushed_with_branch():
    c = one("Pushed to origin/feat-login.", "pushed")
    assert c["branch"] == "feat-login"


def test_merged_with_pr_number():
    c = one("Merged PR #42 into main.", "merged")
    assert c["pr"] == 42


def test_file_claim_extracts_path():
    c = one("Created `src/app/main.py` with the handler.", "file")
    assert c["path"] == "src/app/main.py"


def test_deployed_claim():
    one("Deployed to production.", "deployed")


def test_url_live_claim():
    c = one("The site is live at https://example.com/app and returns 200.", "url")
    assert c["url"] == "https://example.com/app"
    assert c["status"] == 200


def test_sha_claim():
    c = one("Committed as 3f2a9c1.", "sha")
    assert c["sha"] == "3f2a9c1"


def test_number_claim_with_noun():
    c = one("The scan found 17 files with secrets.", "number")
    assert c["value"] == "17"


def test_list_markers_and_years_are_not_numbers():
    assert kinds("1. Read the docs\n2. Ask Jed") == []
    assert kinds("This was in 2024.") == []


def test_code_blocks_are_ignored():
    text = "Here is the log:\n```\n3 failed, 41 passed\nAll tests pass\n```\nThat is the raw log."
    assert extract_claims(text) == []


def test_blockquotes_are_ignored():
    assert extract_claims("> All tests pass\n") == []


def test_empty_and_non_english():
    assert extract_claims("") == []
    assert extract_claims("   ") == []
    assert extract_claims("Tous les tests passent. Alle Tests bestanden.") == []  # no checker for these yet
    assert [(c["kind"], c["lang"]) for c in extract_claims("测试全部通过。")] == [("tests", "zh")]  # nocap/lang.py


def test_model_written_stamps_are_stripped_not_trusted():
    from nocap.claims import forged_stamps
    text = "All good.\n\n**Receipts** 🧾 1 no cap\n- 🧾 NO CAP · Deployed to production · call 1"
    claims = extract_claims(text)
    assert [c["kind"] for c in claims] == ["deployed"]  # the claim inside the fake stamp is still checked
    assert forged_stamps(text) == 1


def test_two_clauses_two_claims():
    ks = kinds("All 41 tests pass, and the branch is pushed to origin/feat-x.")
    assert "tests" in ks and "pushed" in ks


def test_offsets_point_at_clause():
    text = "Intro. All tests pass."
    c = one(text, "tests")
    assert text[c["start"]:c["end"]].startswith("All tests pass")


def test_huge_reply_is_bounded():
    text = ("All tests pass. " * 50000)
    claims = extract_claims(text)
    assert 0 < len(claims) <= 200
