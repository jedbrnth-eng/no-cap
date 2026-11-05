"""The opt-in HTTP self-check (`self_verify_http`): public addresses only, one HEAD, no redirects, short timeout."""
import http.server
import socket
import threading
import time

import pytest

from nocap import verify
from nocap.verdict import CAP, NO_CAP, NO_RECEIPT


def rec(url, text="It is live", status=None):
    return {"kind": "url", "text": text, "verdict": NO_RECEIPT, "claim": {"kind": "url", "url": url, "status": status}}


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "create_connection", boom)
    return calls


BLOCKED = ["http://127.0.0.1:1/x", "http://localhost/", "https://169.254.169.254/latest/meta-data/",
           "http://[::1]/", "http://10.0.0.5/", "http://192.168.1.1/admin", "http://172.16.0.1/",
           "http://[::ffff:127.0.0.1]/", "http://metadata.google.internal/computeMetadata/v1/",
           "http://100.100.100.200/latest/meta-data/", "http://[fd00:ec2::254]/", "http://0.0.0.0/",
           "http://printer.local/", "http://[fe80::1]/", "http://224.0.0.1/", "http://2130706433/",
           "http://0x7f.0.0.1/", "http://127.1/"]


@pytest.mark.parametrize("url", BLOCKED)
def test_non_public_hosts_are_refused_before_any_connection(url, no_network):
    assert verify.recheck(rec(url), "", allow_http=True) is None
    assert no_network == []


def test_dns_answer_with_a_private_address_is_refused(monkeypatch, no_network):
    monkeypatch.setattr(verify, "_resolve", lambda host, port: ["93.184.216.34", "10.1.2.3"])
    assert verify.recheck(rec("https://rebind.example/"), "", allow_http=True) is None
    monkeypatch.setattr(verify, "_resolve", lambda host, port: ["169.254.169.254"])
    assert verify.recheck(rec("https://meta.example/"), "", allow_http=True) is None
    assert no_network == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "//example.com"])
def test_only_http_and_https(url, no_network):
    assert verify.recheck(rec(url), "", allow_http=True) is None
    assert no_network == []


def test_off_by_default(no_network):
    assert verify.recheck(rec("https://example.com/"), "", allow_http=False) is None
    assert no_network == []


class _Server:
    """A local server standing in for a public host (the address check is bypassed for it in these tests)."""

    def __init__(self, status=200, location=None, delay=0.0):
        seen = self.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                seen.append((self.command, self.path, self.headers.get("Host")))
                time.sleep(delay)
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
            do_HEAD = do_GET = do_POST = _answer

            def log_message(self, *a):
                pass
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def public_loopback(monkeypatch):
    """Resolve site.example to 127.0.0.1 and treat that one address as public, so a real request can be made."""
    monkeypatch.setattr(verify, "_resolve", lambda host, port: ["127.0.0.1"] if host == "site.example" else [])
    real = verify._blocked_ip
    monkeypatch.setattr(verify, "_blocked_ip", lambda ip: False if ip == "127.0.0.1" else real(ip))


def test_real_head_request_pinned_to_the_checked_address(public_loopback):
    s = _Server(200)
    try:
        r = verify.recheck(rec(f"http://site.example:{s.port}/health?x=1"), "", allow_http=True)
        assert r[0] == NO_CAP and "HTTP 200" in r[1]
        assert s.seen == [("HEAD", "/health?x=1", f"site.example:{s.port}")]
    finally:
        s.close()


def test_404_is_cap(public_loopback):
    s = _Server(404)
    try:
        assert verify.recheck(rec(f"http://site.example:{s.port}/gone"), "", allow_http=True)[0] == CAP
    finally:
        s.close()


def test_redirects_are_not_followed(public_loopback):
    s = _Server(302, location="http://169.254.169.254/latest/meta-data/")
    try:
        assert verify.recheck(rec(f"http://site.example:{s.port}/"), "", allow_http=True) is None
        assert [m for m, _, _ in s.seen] == ["HEAD"]  # one request, no second hop (and never a GET)
    finally:
        s.close()


def test_short_timeout(public_loopback, monkeypatch):
    monkeypatch.setattr(verify, "HTTP_TIMEOUT", 0.3)
    s = _Server(200, delay=2.0)
    try:
        t = time.perf_counter()
        assert verify.recheck(rec(f"http://site.example:{s.port}/slow"), "", allow_http=True) is None
        assert time.perf_counter() - t < 1.5
    finally:
        s.close()
