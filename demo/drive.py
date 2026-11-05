"""Drive a real interactive Hermes CLI in a pseudo-terminal and record what it prints.

No keystroke is faked into the output: the bytes Hermes writes to the pty are fed into a VT100 emulator
(pyte) and the emulated screen is saved, together with a raw asciicast v2 recording of the whole session.

    uv run --with pyte python3 demo/drive.py --out docs/media/run   (run_demo.sh sets HERMES_HOME etc.)

Steps come from a JSON list on --steps: {"send": "text"} types a line and presses Enter;
{"wait": "regex", "timeout": 60} waits for the regex on screen; {"quiet": 2.5} waits until the screen has been
still that long; {"snap": "name"} saves name.txt (screen + scrollback) and name.html (colours kept);
{"shell": "cmd"} runs a shell command beside the session (e.g. `hermes config set ...`).
{"wait": ..., "since_send": true} only matches output after the last send; {"paste_steer": true, "optional": true}
skips when /cap printed no steer (a real model's reply may have nothing to cap).
"""
from __future__ import annotations

import argparse
import fcntl
import html
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path

import pyte

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--steps", required=True, help="JSON file with the step list")
ap.add_argument("--cols", type=int, default=118)
ap.add_argument("--rows", type=int, default=48)
ap.add_argument("--cmd", default="hermes")
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
steps = json.loads(Path(a.steps).read_text())

screen = pyte.HistoryScreen(a.cols, a.rows, history=5000, ratio=0.5)
stream = pyte.ByteStream(screen)
lock = threading.Lock()
last_change = [time.time()]
cast = open(out / "session.cast", "w", encoding="utf-8")
cast.write(json.dumps({"version": 2, "width": a.cols, "height": a.rows, "timestamp": int(time.time()),
                       "env": {"TERM": "xterm-256color"}, "title": "No Cap demo (real Hermes CLI)"}) + "\n")
t0 = time.time()

pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-256color"
    os.environ["COLUMNS"], os.environ["LINES"] = str(a.cols), str(a.rows)
    os.execvp("sh", ["sh", "-c", a.cmd])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", a.rows, a.cols, 0, 0))
alive = [True]


def reader():
    while alive[0]:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            data = os.read(fd, 65536)
        except OSError:
            alive[0] = False
            break
        if not data:
            alive[0] = False
            break
        with lock:
            # U+FE0F (emoji presentation selector) desyncs pyte's cell widths and eats the rest of the line;
            # drop it for the emulated screen only (the .cast keeps the original bytes)
            stream.feed(data.replace(b"\xef\xb8\x8f", b""))
            last_change[0] = time.time()
            cast.write(json.dumps([round(time.time() - t0, 4), "o", data.decode("utf-8", "replace")]) + "\n")
            cast.flush()
            # answer cursor-position queries so prompt_toolkit doesn't wait for a real terminal
            if b"\x1b[6n" in data:
                os.write(fd, f"\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}R".encode())


threading.Thread(target=reader, daemon=True).start()


def lines(with_history=True):
    with lock:
        rows = []
        if with_history:
            for row in list(screen.history.top):
                rows.append([row[x] for x in range(a.cols)])
        for y in range(a.rows):
            rows.append([screen.buffer[y][x] for x in range(a.cols)])
    return rows


def text_of(rows):
    return "\n".join("".join(c.data for c in r).rstrip() for r in rows).rstrip() + "\n"


COLORS = {"black": "#0E0F12", "red": "#FF6B61", "green": "#2BD67B", "brown": "#FFB627", "yellow": "#FFD166",
          "blue": "#7AA2F7", "magenta": "#C792EA", "cyan": "#5FD7D7", "white": "#E6E6E6", "default": None}


def color(c, fallback):
    if c in COLORS:
        return COLORS[c] or fallback
    if re.fullmatch(r"[0-9a-fA-F]{6}", c or ""):
        return "#" + c
    return fallback


def html_of(rows, title):
    body = []
    for r in rows:
        spans, cur, buf = [], None, []
        for ch in r:
            style = (color(ch.fg, "#E6E6E6") if not ch.reverse else "#0E0F12",
                     None if ch.bg == "default" and not ch.reverse else (color(ch.bg, None) if not ch.reverse else "#E6E6E6"),
                     ch.bold)
            if style != cur and buf:
                spans.append((cur, "".join(buf)))
                buf = []
            cur = style
            buf.append(ch.data)
        if buf:
            spans.append((cur, "".join(buf)))
        line = ""
        for (fg, bg, bold), s in spans:
            css = f"color:{fg};" + (f"background:{bg};" if bg else "") + ("font-weight:700;" if bold else "")
            line += f'<span style="{css}">{html.escape(s)}</span>'
        body.append(line.rstrip())
    while body and not re.sub(r"<[^>]+>", "", body[-1]).strip():
        body.pop()
    return ("<!doctype html><html><head><meta charset='utf-8'><title>" + html.escape(title) + "</title><style>"
            "html,body{margin:0;background:#0E0F12}"
            "pre{margin:0;padding:28px 32px;font:15px/1.35 ui-monospace,'SF Mono',Menlo,monospace;color:#E6E6E6;"
            "white-space:pre}</style></head><body><pre>" + "\n".join(body) + "</pre></body></html>")


def wait_quiet(secs, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        if time.time() - last_change[0] >= secs:
            return True
        time.sleep(0.2)
    return False


def wait_for(pattern, timeout=60, since=0):
    rx = re.compile(pattern)
    end = time.time() + timeout
    while time.time() < end:
        if rx.search(text_of(lines()[since:])):
            return True
        time.sleep(0.3)
    return False


def here():
    """Index (in lines()) of the cursor row: where the next output lands."""
    with lock:
        return len(screen.history.top) + screen.cursor.y


def send(text):
    for ch in text:
        os.write(fd, ch.encode())
        time.sleep(0.03)
    time.sleep(0.3)
    os.write(fd, b"\r")


log = []
mark = 0
for st in steps:
    if "send" in st:
        mark = here()  # snap windows start at the line being typed
        send(st["send"])
        log.append(f"send {st['send']!r}")
    elif "wait" in st:
        ok = wait_for(st["wait"], st.get("timeout", 60), since=mark if st.get("since_send") else 0)
        log.append(f"wait {st['wait']!r}: {'ok' if ok else 'TIMEOUT'}")
        if not ok and st.get("required", True):
            (out / "TIMEOUT.txt").write_text(text_of(lines()))
            print("\n".join(log), "\nTIMEOUT waiting for", st["wait"], file=sys.stderr)
            alive[0] = False
            os.kill(pid, signal.SIGTERM)
            sys.exit(3)
    elif "quiet" in st:
        wait_quiet(st["quiet"], st.get("timeout", 120))
        log.append(f"quiet {st['quiet']}")
    elif "sleep" in st:
        time.sleep(st["sleep"])
    elif "shell" in st:
        r = subprocess.run(st["shell"], shell=True, capture_output=True, text=True)
        log.append(f"shell {st['shell']!r} → exit {r.returncode}")
    elif "snap" in st:
        rows = lines()
        name = st["snap"]
        (out / f"{name}.txt").write_text(text_of(rows), encoding="utf-8")
        (out / f"{name}.screen.txt").write_text(text_of(rows[-a.rows:]), encoding="utf-8")
        tail = rows[max(0, mark - st.get("before", 1)):] if st.get("from_last_send", True) else rows[-a.rows:]
        (out / f"{name}.html").write_text(html_of(tail, name), encoding="utf-8")
        log.append(f"snap {name}")
    elif "paste_steer" in st:
        # do what /cap tells the user when Hermes won't let a plugin inject: paste the printed steer back
        # the TUI frames text: a right-hand rail (┃) on the transcript, a ║ box around overlays such as /cap's
        rows = [re.sub(r"\s*[┃║]\s*$", "", re.sub(r"^\s*║", "", l)) for l in text_of(lines()).splitlines()]
        starts = [i for i, l in enumerate(rows) if l.lstrip().startswith("[No Cap] I'm calling cap")]
        if not starts and st.get("optional"):
            log.append("paste_steer: no steer on screen, skipped")
            continue
        start = max(starts)
        margin = len(rows[start]) - len(rows[start].lstrip())  # the TUI indents its transcript; the CLI doesn't
        steer = []
        for l in rows[start:]:
            if not l.strip():
                break
            l = l[margin:] if l[:margin].strip() == "" else l
            if steer and not re.match(r"^\d+\. ", l):
                # a soft wrap: the CLI cuts mid-word (join as is), the TUI wraps at a space (put it back)
                steer[-1] += (" " + l.lstrip()) if margin else l
            else:
                steer.append(l)
        if st.get("close_overlay"):  # the TUI shows /cap's output in an overlay: read it, then Esc closes it
            os.write(fd, b"\x1b")
            time.sleep(1)
        mark = here()
        os.write(fd, b"\x1b[200~" + "\n".join(steer).encode() + b"\x1b[201~")
        time.sleep(0.5)
        os.write(fd, b"\r")
        log.append(f"paste_steer ({len(steer)} lines)")
    elif "key" in st:
        os.write(fd, {"ctrl-c": b"\x03", "ctrl-d": b"\x04", "enter": b"\r", "esc": b"\x1b"}[st["key"]])

(out / "driver.log").write_text("\n".join(log) + "\n")
alive[0] = False
try:
    os.kill(pid, signal.SIGTERM)
except ProcessLookupError:
    pass
cast.close()
print("\n".join(log))
