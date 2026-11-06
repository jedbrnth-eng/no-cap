#!/usr/bin/env python3
"""Check that every link and image in the docs resolves.

    python scripts/check_links.py            # local files and #anchors (offline, also run by the test suite)
    python scripts/check_links.py --online   # also fetch every http(s) link (HEAD, then GET on 405/403)

Checks README.md, CHANGELOG.md, SECURITY.md and docs/**/*.md: markdown links and images, and HTML src/href.
Exit 1 and a list of broken links when anything is missing.
"""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_LINK = re.compile(r"""(?:src|href)=["']([^"']+)["']""")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def docs():
    files = [ROOT / n for n in ("README.md", "CHANGELOG.md", "SECURITY.md") if (ROOT / n).exists()]
    return files + sorted((ROOT / "docs").rglob("*.md"))


def slug(heading):
    """GitHub's heading anchor: lowercase, drop punctuation and emoji, spaces to hyphens."""
    h = re.sub(r"<[^>]+>", "", heading).strip().lower()
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")


def anchors(path):
    text = CODE.sub("", path.read_text(encoding="utf-8"))
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M)}


def links(path):
    text = CODE.sub("", path.read_text(encoding="utf-8"))
    return [m.group(1) for rx in (MD_LINK, HTML_LINK) for m in rx.finditer(text)]


def check_local(path, target):
    if target.startswith(("mailto:", "data:")):
        return None
    ref, _, frag = target.partition("#")
    dest = path if not ref else (path.parent / ref).resolve()
    if ROOT not in dest.parents and dest != ROOT:
        return f"points outside the repo: {target}"
    if not dest.exists():
        return f"missing file: {target}"
    if frag and dest.suffix == ".md" and frag not in anchors(dest):
        return f"missing anchor: {target}"
    return None


def check_online(url):
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "no-cap-link-check"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310: https/http links from our own docs
                if r.status < 400:
                    return None
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 429):
                continue
            return f"HTTP {e.code}: {url}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return f"unreachable ({e}): {url}"
    return f"no 2xx/3xx: {url}"


def main(argv):
    online = "--online" in argv
    problems, n = [], 0
    seen_urls = {}
    for path in docs():
        for target in links(path):
            n += 1
            if target.startswith(("http://", "https://")):
                if online:
                    if target not in seen_urls:
                        seen_urls[target] = check_online(target)
                    err = seen_urls[target]
                else:
                    err = None
            else:
                err = check_local(path, target)
            if err:
                problems.append(f"{path.relative_to(ROOT)}: {err}")
    for p in problems:
        print(p)
    print(f"{n} links checked in {len(docs())} files ({'local + online' if online else 'local only'}), "
          f"{len(problems)} broken")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
