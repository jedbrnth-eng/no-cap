"""Self-verify for /cap: cheap, read-only re-checks of unproven claims.

Only these run, and only with argv lists (no shell):
  * file claims: os.stat of the path (relative paths resolved against the session cwd)
  * sha / commit claims: `git -C <cwd> cat-file -t <sha>`
  * push claims with a branch: `git -C <cwd> rev-parse --verify <ref>` for the local branch and its
    origin remote-tracking ref (no fetch, so no network)
  * url claims: one HTTP HEAD request, only when the user turns on `self_verify_http`, only to a public address
    (checked after DNS resolution), no redirects, 3 s timeout (see http_head)
Everything else (tests, merges, deploys, numbers) becomes a suggested command in the /cap steer.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
import re
import socket
import ssl
import subprocess
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .verdict import CAP, NO_CAP

SHA_OK = re.compile(r"^[0-9a-f]{7,40}$")
REF_OK = re.compile(r"^(?!-)[\w./-]{1,200}$")
READ_ONLY_GIT = {("cat-file", "-t"), ("rev-parse", "--verify")}
TIMEOUT = 5
CREATE_VERBS = re.compile(r"\b(creat\w*|add(ed|s)?|wr[io]te|written|sav(ed|es)|generat\w*|new file|scaffold\w*|"
                          r"exports?|exported|dump(ed)?|copied|moved|renamed|made)\b")


def _git(cwd: str, sub: Tuple[str, str], arg: str) -> Optional[str]:
    if sub not in READ_ONLY_GIT or not cwd or not os.path.isdir(cwd):
        return None
    argv = ["git", "-C", cwd, sub[0], sub[1], arg]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    except Exception:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _file(r, cwd) -> Optional[Tuple[str, str]]:
    raw = r["claim"].get("path", "")
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        if not cwd:
            return None
        p = Path(cwd) / p
    verb = r.get("text", "").lower()
    if p.exists():
        if not CREATE_VERBS.search(verb):
            return None  # the file being there proves it exists, not that it was fixed or changed
        size = p.stat().st_size if p.is_file() else 0
        return NO_CAP, f"{raw} exists ({size:,} bytes)" if p.is_file() else f"{raw} exists"
    if re.search(r"\b(deleted|removed)\b", verb):
        return NO_CAP, f"{raw} is gone"
    return None  # absent but maybe created elsewhere: a hint, not a 🧢


def _sha(r, cwd) -> Optional[Tuple[str, str]]:
    sha = r["claim"].get("sha") or ""
    if not SHA_OK.match(sha):
        return None
    kind = _git(cwd, ("cat-file", "-t"), sha)
    if kind == "commit":
        return NO_CAP, f"git has commit {sha}"
    return None


def _pushed(r, cwd) -> Optional[Tuple[str, str]]:
    b = r["claim"].get("branch") or ""
    if not REF_OK.match(b):
        return None
    local = _git(cwd, ("rev-parse", "--verify"), f"refs/heads/{b}")
    remote = _git(cwd, ("rev-parse", "--verify"), f"refs/remotes/origin/{b}")
    if local and remote and local == remote:
        return NO_CAP, f"origin/{b} = local {b} at {local[:7]} (local tracking ref)"
    return None


HTTP_TIMEOUT = 3.0
_BLOCKED_NAMES = re.compile(r"(?i)^(?:localhost|.*\.localhost|.*\.local|.*\.internal|.*\.localdomain|.*\.home\.arpa|"
                            r"metadata|metadata\.google\.internal|instance-data(?:\..*)?)\.?$")


def _resolve(host: str, port: int) -> List[str]:
    """Every address the host resolves to (an IP literal resolves to itself, in any of the forms inet_aton takes)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _blocked_ip(ip: str) -> bool:
    """Anything that isn't a plain public unicast address: loopback, link-local (cloud metadata 169.254.169.254),
    private, carrier-grade NAT (100.64/10, e.g. 100.100.100.200), unique-local IPv6 (fd00:ec2::254), multicast,
    reserved, unspecified, and IPv4-mapped / NAT64 forms of those."""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(a, ipaddress.IPv6Address):
        inner = a.ipv4_mapped or a.sixtofour or (a.teredo[1] if a.teredo else None)
        if inner is None and a in ipaddress.ip_network("64:ff9b::/96"):
            inner = ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)
        if inner is not None and _blocked_ip(str(inner)):
            return True
    return not a.is_global or a.is_multicast or a.is_reserved or a.is_loopback or a.is_link_local or a.is_private


class _PinnedHTTP(http.client.HTTPConnection):
    """Connects to the address that was checked, not to a fresh DNS answer (no rebinding between check and use)."""

    def __init__(self, ip: str, host: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, ip: str, host: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def http_head(url: str) -> Optional[int]:
    """One HEAD request to a public address, or None. The host is resolved first and refused if any address it
    resolves to is not public; the connection goes to that checked address; redirects are not followed (a 3xx is
    returned as is); HTTP_TIMEOUT seconds to connect and to read."""
    try:
        u = urlsplit(url)
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return None
    host = u.hostname or ""
    if u.scheme not in ("http", "https") or not host or _BLOCKED_NAMES.match(host):
        return None
    try:
        ips = _resolve(host, port)
    except (OSError, UnicodeError):
        return None
    if not ips or any(_blocked_ip(ip) for ip in ips):
        return None
    conn_cls = _PinnedHTTPS if u.scheme == "https" else _PinnedHTTP
    conn = conn_cls(ips[0], host, port, HTTP_TIMEOUT)
    try:
        conn.request("HEAD", (u.path or "/") + (f"?{u.query}" if u.query else ""),
                     headers={"User-Agent": "no-cap-self-verify", "Accept": "*/*"})
        return conn.getresponse().status
    except (OSError, http.client.HTTPException, ValueError):
        return None
    finally:
        conn.close()


def _url(r, allow_http) -> Optional[Tuple[str, str]]:
    if not allow_http:
        return None
    url = r["claim"].get("url", "")
    code = http_head(url)
    if code is None or 300 <= code < 400:
        return None  # refused, unreachable, or a redirect we don't follow: no verdict
    want = r["claim"].get("status")
    if code in (404, 410) or code >= 500 or (want and code < 400 and code != want and want >= 400):
        return CAP, f"HEAD {url} → HTTP {code}"
    if code < 400 and (not want or want == code or (want < 400 and code < 400)):
        return NO_CAP, f"HEAD {url} → HTTP {code}"
    return None  # 401/403/405 on HEAD prove nothing either way


_PLAIN_WORD = r"[\w./:=@,+%~-]+"
_PLAIN_CMD_RE = re.compile(rf"{_PLAIN_WORD}(?: {_PLAIN_WORD}){{0,20}}")
_PLAIN_URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@%=+,-]{1,300}")
_PLAIN_PATH_RE = re.compile(r"(?!-)[\w./@~+-]{1,200}")
SUITE = "run your test suite"


def _public_name(url: str) -> bool:
    """No DNS here: refuse IP literals that aren't public and local/metadata names, so the steer never asks for a
    request to 169.254.169.254 or localhost."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    if not host or _BLOCKED_NAMES.match(host):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return not re.fullmatch(r"[\d.]+|0x[\da-f.x]+", host, re.I)  # 2130706433, 0x7f.1: odd IPv4 spellings
    return not _blocked_ip(host)


def plain_test_command(cmd: str) -> str:
    """The test-runner part of an earlier command, if it is a plain command line: no chaining, pipes, redirects,
    substitutions, quotes or masked secrets. Else "". The /cap steer quotes nothing else the agent ran."""
    from .evidence import TEST_CMD_RE, runner_segment
    seg = runner_segment((cmd or "").replace(" ⏎ ", "\n"))
    seg = re.sub(r"\s+[12]?>&[12]\b", " ", seg).strip()  # `2>&1` only joins two streams
    seg = re.sub(r"\s+", " ", seg)
    if not seg or len(seg) > 120 or "[redacted]" in seg or not _PLAIN_CMD_RE.fullmatch(seg) or \
            not TEST_CMD_RE.search(seg):
        return ""
    return seg


def suggestion(r: Dict[str, Any], test_cmds: List[str]) -> str:
    """What the /cap steer asks for. Only fixed read-only checks with validated arguments, or a plain test command
    parsed from an earlier run; never a command line copied whole (it could chain `; curl ... | sh`)."""
    k, c = r["kind"], r["claim"]
    if k == "tests":
        plain = next((p for p in (plain_test_command(t) for t in reversed(test_cmds or [])) if p), "")
        return f"run `{plain}`" if plain else SUITE
    if k == "merged":
        pr = c.get("pr")
        return f"run `gh pr view {pr} --json state,mergeCommit`" if isinstance(pr, int) else "show the merge output"
    if k == "pushed":
        b = c.get("branch") or ""
        return f"run `git ls-remote origin {b}`" if b and REF_OK.match(b) else "run `git status -sb`"
    if k == "url":
        u = c.get("url") or ""
        return f"run `curl -sI {u}`" if _PLAIN_URL_RE.fullmatch(u) and _public_name(u) else \
            "show the HTTP status of that URL"
    if k == "file":
        p = c.get("path") or ""
        return f"run `ls -l {p}`" if _PLAIN_PATH_RE.fullmatch(p) else "show that the file exists"
    if k in ("sha", "committed"):
        sha = c.get("sha") or ""
        return f"run `git log -1 --oneline {sha if SHA_OK.match(sha) else 'HEAD'}`"
    if k == "deployed":
        return "show the deploy output or curl the live URL"
    if k == "ci":
        return "run `gh pr checks`"
    if k == "build":
        return "run the build"
    if k == "pr_opened":
        return "run `gh pr view --json url,state`"
    return "show the tool output this came from"


def recheck(r: Dict[str, Any], cwd: str, allow_http: bool = False) -> Optional[Tuple[str, str]]:
    k = r["kind"]
    if r.get("verdict") == CAP:
        return None  # a contradiction in this turn's own output stands; a local re-check can't overrule it
    try:
        if k == "file":
            return _file(r, cwd)
        if k in ("sha", "committed") and r["claim"].get("sha"):
            return _sha(r, cwd)
        if k == "pushed":
            return _pushed(r, cwd)
        if k == "url":
            return _url(r, allow_http)
    except Exception:
        return None
    return None
