"""A URL claim ("https://x is live", "returns 200") needs a call that REQUESTED that URL, and that URL's own status.

Before this file's fix, any successful non-terminal tool whose arguments or output merely contained the URL (a
write_file, a read_file, a search result) stamped the claim 🧾 "<tool> fetched it", any failed one stamped it 🧢,
and a command's last HTTP status was credited to every URL the call mentioned.
"""
import json

from nocap.claims import extract_claims
from nocap.evidence import extract
from nocap.verdict import judge

URL = "https://example.com/health"
LIVE = f"{URL} is live."


def term(i, cmd, output, exit_code=0):
    return extract("terminal", {"command": cmd}, json.dumps({"output": output, "exit_code": exit_code}), index=i)


def tool(i, name, args, result, status="ok"):
    return extract(name, args, json.dumps(result), status=status, index=i)


def url_receipts(reply, evidence):
    return [r for r in judge(extract_claims(reply), evidence) if r["kind"] == "url"]


def verdicts(reply, evidence):
    return [r["verdict"] for r in url_receipts(reply, evidence)]


# ---- a call that only names the URL is not a fetch ------------------------------------------------------------------
def test_url_written_into_a_file_is_not_a_fetch():
    ev = [tool(1, "write_file", {"path": "README.md", "content": f"See {URL}"}, {"bytes_written": 40})]
    r = url_receipts(LIVE, ev)[0]
    assert r["verdict"] == "NO_RECEIPT"
    assert r["cite"] == 1 and "not requested" in r["why"]


def test_url_read_from_a_file_is_not_a_fetch():
    ev = [tool(1, "read_file", {"path": "README.md"}, {"content": f"1|See {URL}", "total_lines": 1})]
    assert verdicts(f"{URL} is live and returns 200.", ev) == ["NO_RECEIPT"]


def test_url_in_a_search_result_is_not_a_fetch():
    ev = [tool(1, "web_search", {"query": "example health"}, {"data": {"web": [{"url": URL, "title": "t"}]}})]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


def test_url_in_a_patch_is_not_a_fetch():
    ev = [tool(1, "patch", {"path": "README.md", "old_string": "a", "new_string": f"Docs: {URL}"}, {"success": True})]
    assert verdicts(f"{URL} returns 200.", ev) == ["NO_RECEIPT"]


def test_failed_write_that_names_the_url_is_not_a_contradiction():
    ev = [tool(1, "write_file", {"path": "/etc/motd", "content": f"See {URL}"}, {"error": "Permission denied"},
               status="error")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


def test_url_only_printed_by_a_command_is_not_a_fetch():
    ev = [term(1, "git remote -v && curl -s -o /dev/null -w '%{http_code}' https://other.example.org",
               f"origin\t{URL} (fetch)\n200")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]
    ev = [term(1, "cat notes/deploy.txt", f"deployed {URL}\nlast check: HTTP/2 200\n")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]
    ev = [term(1, f"echo {URL}", URL)]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


def test_url_named_by_git_in_a_command_that_curls_something_else():
    ev = [term(1, f"git remote set-url origin {URL} && curl -sI $HEALTH", "HTTP/2 200 \n")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


# ---- fetch tools ---------------------------------------------------------------------------------------------------
def test_fetch_tool_that_requested_the_url_is_a_receipt():
    ev = [tool(1, "web_extract", {"urls": [URL]}, {"results": [{"url": URL, "content": "ok", "error": None}]})]
    r = url_receipts(LIVE, ev)[0]
    assert (r["verdict"], r["quote"]) == ("NO_CAP", "web_extract fetched it")
    ev = [tool(1, "browser_navigate", {"url": URL}, {"success": True, "title": "ok"})]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    ev = [tool(1, "mcp__browser__open", {"url": URL}, {"ok": True})]
    assert verdicts(LIVE, ev) == ["NO_CAP"]


def test_fetch_tool_per_url_error_is_not_a_receipt():
    ev = [tool(1, "web_extract", {"urls": ["https://example.com/a", URL]},
               {"results": [{"url": "https://example.com/a", "content": "ok", "error": None},
                            {"url": URL, "content": "", "error": "blocked by robots.txt"}]})]
    r = url_receipts(LIVE, ev)[0]
    assert r["verdict"] == "NO_RECEIPT" and "robots" in r["quote"]
    assert verdicts("https://example.com/a is live.", ev) == ["NO_CAP"]  # the other URL of the same call is fine


def test_fetch_tool_per_url_http_error_contradicts():
    ev = [tool(1, "web_extract", {"urls": [URL]}, {"results": [{"url": URL, "content": "", "error": "HTTP 503"}]})]
    r = url_receipts(LIVE, ev)[0]
    assert (r["verdict"], r["quote"]) == ("CAP", "HTTP 503")


def test_fetch_tool_error_with_a_status_still_contradicts():
    ev = [tool(1, "web_extract", {"urls": [URL]}, {"error": "HTTP 502 Bad Gateway"}, status="error")]
    assert verdicts(LIVE, ev) == ["CAP"]
    ev = [tool(1, "browser_navigate", {"url": "http://localhost:3000"}, {"error": "net::ERR_CONNECTION_REFUSED"},
               status="error")]
    assert verdicts("http://localhost:3000 is up.", ev) == ["CAP"]


def test_fetch_tool_that_broke_for_its_own_reasons_is_not_a_contradiction():
    for err in ("web backend not configured: missing API key", "rate limited, retry in 30s", "Timed out after 60s"):
        ev = [tool(1, "web_extract", {"urls": [URL]}, {"error": err}, status="error")]
        r = url_receipts(LIVE, ev)[0]
        assert r["verdict"] == "NO_RECEIPT", err
        assert r["cite"] == 1


# ---- which status belongs to which URL -----------------------------------------------------------------------------
def test_two_urls_in_one_command_each_get_their_own_status():
    out = "HTTP/2 200 \ncontent-type: text/plain\n\nHTTP/2 404 \ncontent-type: text/plain\n"
    ev = [term(1, f"curl -sI {URL} https://example.com/old", out)]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    assert verdicts("https://example.com/old is live.", ev) == ["CAP"]
    ev = [term(1, f"curl -sI https://example.com/new {URL}", out)]
    r = url_receipts(LIVE, ev)[0]
    assert (r["verdict"], r["quote"]) == ("CAP", "HTTP 404")


def test_two_urls_and_a_status_count_that_does_not_match_abstains():
    ev = [term(1, f"curl -sIL {URL} https://example.com/old", "HTTP/2 301 \n\nHTTP/2 200 \n\nHTTP/2 404 \n")]
    r = url_receipts(LIVE, ev)[0]
    assert r["verdict"] == "NO_RECEIPT" and "several URLs" in r["why"]


def test_one_url_and_a_second_request_to_a_variable_abstains():
    ev = [term(1, f"curl -sI {URL}; curl -sI $OTHER", "HTTP/2 404 \n\nHTTP/2 200 \n")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


def test_one_url_keeps_its_last_status():
    ev = [term(1, f"curl -sIL {URL}", "HTTP/2 301 \nlocation: https://www.example.com/health\n\nHTTP/2 200 \n")]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    loop = f"for i in 1 2 3; do curl -s -o /dev/null -w '%{{http_code}}\\n' {URL}; sleep 2; done"
    assert verdicts(LIVE, [term(1, loop, "503\n503\n200\n")]) == ["NO_CAP"]  # a wait-until-healthy loop
    assert verdicts(LIVE, [term(1, loop, "200\n503\n503\n")]) == ["CAP"]
    ev = [term(1, f"curl -s -o /dev/null -w '%{{http_code}}' {URL}", "200")]
    assert verdicts(LIVE, ev) == ["NO_CAP"]


def test_a_script_that_prints_the_url_with_its_status_is_a_receipt():
    ev = [term(1, "python scripts/check_health.py", f"{URL} -> status: 200\nhttps://example.com/old -> status: 404\n")]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    assert verdicts("https://example.com/old is live.", ev) == ["CAP"]
    ev = [term(1, "sh scripts/smoke.sh", f"200 {URL}\n")]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    ev = [term(1, "python scripts/check_health.py", f"checking {URL}\ndone, 3 retries\n")]
    assert verdicts(LIVE, ev) == ["NO_RECEIPT"]


def test_wget_status_line():
    ev = [term(1, f"wget -S --spider {URL}", f"--2026-01-01--  {URL}\nHTTP request sent, awaiting response... 404 Not Found\n", 8)]
    assert verdicts(LIVE, ev) == ["CAP"]


def test_latest_check_of_the_url_wins():
    ev = [term(1, f"curl -sI {URL}", "HTTP/2 404 \n"), term(2, f"curl -sI {URL}", "HTTP/2 200 \n")]
    assert verdicts(LIVE, ev) == ["NO_CAP"]
    ev = [term(1, f"curl -sI {URL}", "HTTP/2 404 \n"), term(2, "echo HTTP/2 200", "HTTP/2 200\n"),
          tool(3, "write_file", {"path": "STATUS.md", "content": f"{URL} is up"}, {"bytes_written": 9})]
    r = url_receipts(LIVE, ev)[0]
    assert (r["verdict"], r["cite"]) == ("CAP", 1)
    # a later check that says something beats an earlier status
    ev = [term(1, "curl -sI http://localhost:3000", "HTTP/1.1 200 OK\n"),
          tool(2, "browser_navigate", {"url": "http://localhost:3000"}, {"error": "net::ERR_CONNECTION_REFUSED"},
               status="error")]
    r = url_receipts("http://localhost:3000 is up.", ev)[0]
    assert (r["verdict"], r["cite"]) == ("CAP", 2)


def test_honest_status_reports_still_match():
    ev = [term(1, f"curl -sI {URL}", "HTTP/2 503 \n")]
    assert verdicts(f"{URL} returns 503.", ev) == ["NO_CAP"]
    assert verdicts(f"{URL} returns 200.", ev) == ["CAP"]
