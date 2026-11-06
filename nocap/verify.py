"""Self-verify for /cap: cheap, read-only re-checks of unproven claims.

Only these run, and only with argv lists (no shell):
  * file claims: os.stat of the path (relative paths resolved against the session cwd)
  * sha / commit claims: `git -C <cwd> cat-file -t <sha>`
  * push claims with a branch: `git -C <cwd> rev-parse --verify <ref>` for the local branch and its
    origin remote-tracking ref (no fetch, so no network)
  * url claims: one HTTP HEAD request, only when the user turns on `self_verify_http`, only to a public address
    (checked after DNS resolution), no redirects, 3 s timeout (see http_head)
Everything else (tests, merges, deploys, numbers) becomes a suggested command in the /cap steer.

Fabricated-artifact detector (reply time, `verify_artifacts`, default on): a claimed SHA that is no object in the
session's repo (`git cat-file -e`) or a claimed branch with no local, remote-tracking or tag ref (`git for-each-ref`)
gets 🧢. Local and read-only, in the session's working dir only.

Every git call here is an argv list (no shell) with a timeout, and is hardened against an untrusted repo's own
config: GIT_CONFIG_NOSYSTEM=1, GIT_CONFIG_GLOBAL=/dev/null, `-c core.hooksPath=/dev/null`, `-c core.fsmonitor=false`,
`-c protocol.allow=never` (no transport, so no network), no pager, no lazy fetch, and inherited GIT_* variables
(GIT_DIR and friends) dropped.
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
REF_OK = re.compile(r"^(?!-)(?!.*\.\.)[\w./-]{1,200}$")
READ_ONLY_GIT = {("cat-file", "-t"), ("rev-parse", "--verify")}
TIMEOUT = 5
ARTIFACT_TIMEOUT = 3
MAX_ARTIFACT_CHECKS = 8  # git calls per reply at most (each well under 50 ms on a normal repo)
HARDEN = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never",
          "-c", "core.pager=cat", "-c", "credential.helper=", "-c", "core.sshCommand=false")


def git_env() -> Dict[str, str]:
    """The environment for every git call: the untrusted repo can't pull in system/global config, hooks, a pager,
    a lazy fetch or a credential prompt, and a GIT_DIR / GIT_WORK_TREE exported by the agent is ignored."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_PAGER": "cat", "PAGER": "cat",
                "GIT_ASKPASS": "", "SSH_ASKPASS": "", "GIT_NO_REPLACE_OBJECTS": "1"})
    return env


def run_git(cwd: str, args: List[str], timeout: float = TIMEOUT) -> Optional[Tuple[int, str, str]]:
    """(returncode, stdout, stderr) of one hardened, read-only git call in cwd, or None if it couldn't run."""
    if not cwd or not os.path.isdir(cwd):
        return None
    argv = ["git", "--no-pager", *HARDEN, "-C", cwd, *args]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=git_env(),  # argv list, no shell
                           stdin=subprocess.DEVNULL, shell=False)
    except Exception:
        return None
    return p.returncode, p.stdout[:200_000], p.stderr[:4000]
CREATE_VERBS = re.compile(r"\b(creat\w*|add(ed|s)?|wr[io]te|written|sav(ed|es)|generat\w*|new file|scaffold\w*|"
                          r"exports?|exported|dump(ed)?|copied|moved|renamed|made)\b")


def _git(cwd: str, sub: Tuple[str, str], arg: str) -> Optional[str]:
    if sub not in READ_ONLY_GIT:
        return None
    res = run_git(cwd, [sub[0], sub[1], arg])
    return res[1].strip() if res and res[0] == 0 else None


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


# ---- fabricated-artifact detector (reply time) ---------------------------------------------------------------------
SHA_CONTEXT_RE = re.compile(r"(?i)\b(?:commit(?:ted|s)?|head|sha|pushed|merged|landed|rev(?:ision)?|cherry-pick\w*|"
                            r"tagged|rebased|reverted|squash\w*|amend\w*)\b")
NOT_GIT_HASH_RE = re.compile(r"(?i)\b(?:md5|sha-?(?:1|224|256|384|512)sum|sha-?256|sha-?512|checksum|digest|hash of|"
                             r"image|container|docker|uuid|request id|trace id|build id|run id|etag|integrity|blob)\b")


def _repo_state(cwd: str) -> Optional[str]:
    """"ok" for a normal work tree (the only kind checked); None if not a repo, shallow, partial or unreadable:
    there an object can be missing locally and still exist, so a missing SHA proves nothing."""
    res = run_git(cwd, ["rev-parse", "--is-inside-work-tree", "--is-shallow-repository"], ARTIFACT_TIMEOUT)
    if not res or res[0] != 0 or res[1].split() != ["true", "false"]:
        return None
    cfg = run_git(cwd, ["config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$"],
                  ARTIFACT_TIMEOUT)
    if cfg is None or cfg[0] not in (0, 1) or cfg[1].strip():
        return None
    return "ok"


def sha_exists(cwd: str, sha: str) -> Optional[bool]:
    """True/False from `git cat-file -e <sha>` (an ambiguous short SHA counts as existing); None if unknown."""
    if not SHA_OK.match(sha or ""):
        return None
    res = run_git(cwd, ["cat-file", "-e", sha], ARTIFACT_TIMEOUT)
    if res is None:
        return None
    code, _, err = res
    if code == 0 or "ambiguous" in err.lower():
        return True
    if code in (1, 128) and (not err.strip() or re.search(r"(?i)not a valid object name", err)):
        return False
    return None


def branch_exists(cwd: str, branch: str) -> Optional[bool]:
    """Is there a local branch, a remote-tracking branch on any remote, or a tag with that name? None if unknown."""
    if not REF_OK.match(branch or ""):
        return None
    res = run_git(cwd, ["for-each-ref", "--format=%(refname)", "refs/heads/", "refs/remotes/", "refs/tags/"],
                  ARTIFACT_TIMEOUT)
    if res is None or res[0] != 0:
        return None
    refs = set(res[1].splitlines())
    if f"refs/heads/{branch}" in refs or f"refs/tags/{branch}" in refs:
        return True
    return any(r.startswith("refs/remotes/") and r.split("/", 3)[-1] == branch for r in refs if r.count("/") >= 3)


def _same_repo(where: str, cwd: str) -> bool:
    if not where or where in (".", "./"):
        return True
    try:
        w = Path(os.path.expanduser(where))
        w = w if w.is_absolute() else Path(cwd) / w
        return os.path.realpath(w) == os.path.realpath(cwd)
    except Exception:
        return False


def check_artifacts(receipts: List[Dict[str, Any]], cwd: str, session_evs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn 🤔 into 🧢 for a claimed SHA that isn't an object in the session's repo, or a claimed branch that no ref
    has. Only unproven receipts are looked at, only when every git call of the session ran in this repo, and never
    for a SHA or branch that any tool output or command of the session named (it may live in another clone, or have
    been deleted after a merge)."""
    from .verdict import CAP, NO_RECEIPT
    todo = [r for r in receipts if r.get("verdict") == NO_RECEIPT and (
        (r["kind"] in ("sha", "committed") and (r.get("claim") or {}).get("sha"))
        or (r["kind"] == "pushed" and (r.get("claim") or {}).get("branch")))]
    if not todo or not cwd:
        return receipts
    if any(e.get("where") and re.search(r"(?:^|&&|;)\s*cd\s|\bgit\s", str(e.get("cmd") or ""))
           and not _same_repo(str(e["where"]), cwd) for e in session_evs or []):
        return receipts  # the session worked in another repo too: the artifact may live there
    if _repo_state(cwd) != "ok":
        return receipts
    seen_shas = [str(s) for e in session_evs or [] for s in (e.get("shas") or []) + [e.get("head_sha") or ""] if s]
    seen_shas += [str((e.get("git") or {}).get("commit") or "") for e in session_evs or []]
    cmds = " ".join(str(e.get("cmd") or "") for e in session_evs or [])
    out, n = [], 0
    for r in receipts:
        if r not in todo or n >= MAX_ARTIFACT_CHECKS:
            out.append(r)
            continue
        c = r.get("claim") or {}
        text = r.get("text") or ""
        if r["kind"] in ("sha", "committed"):
            sha = str(c.get("sha") or "").lower()
            if not (7 <= len(sha) <= 12 or len(sha) == 40) or any(x and (x.startswith(sha) or sha.startswith(x))
                                                                    for x in seen_shas if len(x) >= 7):
                out.append(r)
                continue
            if not SHA_CONTEXT_RE.search(text) or NOT_GIT_HASH_RE.search(text):
                out.append(r)
                continue
            n += 1
            if sha_exists(cwd, sha) is False:
                r = dict(r, verdict=CAP, why="sha not found in repo", quote=f"git cat-file -e {sha}: sha not found in repo",
                         artifact=True)
        else:
            b = str(c.get("branch") or "")
            if re.search(r"(?<![\w/.-])" + re.escape(b) + r"(?![\w/-])", cmds):
                out.append(r)
                continue
            n += 1
            if branch_exists(cwd, b) is False:
                r = dict(r, verdict=CAP, why=f"branch {b} not found in repo",
                         quote=f"no refs/heads/{b} and no remote-tracking ref for it", artifact=True)
        out.append(r)
    return out
