"""Scan tracked text for personal home paths and non-example email addresses."""
import re
import subprocess
from pathlib import Path

HOME = re.compile(r'(^|[^\w./-])(/Users/[A-Za-z][^\s"\x27]*|/home/[a-z][a-z0-9_-]*/)', re.M)
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
ALLOWED = {'example.com', 'example.org', 'example.net', 'users.noreply.github.com'}


ANSI = re.compile(r'(?:\x1b|\\u001[bB]|\\x1[bB])\[[0-?]*[ -/]*[@-~]')
# A diff's added decorator has no email local part. Strip only its leading '+',
# not the line: an actual address later on that same line must still fail.
DECORATOR = re.compile(r'(^|[\s]|\\n)\+(@pytest\.mark\.[A-Za-z_]\w*)')


def findings(text):
    text = DECORATOR.sub(r'\1\2', ANSI.sub('', text))
    hits = ['home path' for _ in HOME.finditer(text)]
    hits += ['email' for m in EMAIL.finditer(text) if m.group().rsplit('@', 1)[1].lower() not in ALLOWED]
    return hits


def main():
    files = subprocess.run(['git', 'ls-files', '-z'], check=True, capture_output=True).stdout.split(b'\0')
    found = False
    for raw in files:
        if not raw:
            continue
        path = Path(raw.decode())
        data = path.read_bytes()
        if b'\0' in data:
            continue
        for number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
            hits = findings(line)
            if hits:
                print(f'{path}:{number}: {", ".join(hits)}')
                found = True
    print('personal data found' if found else 'no home paths or personal emails')
    return int(found)


if __name__ == '__main__':
    raise SystemExit(main())
