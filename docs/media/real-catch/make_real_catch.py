"""Build an asciicast from one real Arena episode's recorded event stream (no text edited), then a GIF + poster.

The source is the episode's stream.jsonl (Hermes `chat -Q --oneshot` JSON events). Tool-call header lines are
formatted here ("● tool  args"); the prompt, every tool output, the model's reply and No Cap's footer are the
recorded bytes. Timing is compressed (87 s -> ~10 s).

    uv run --with pyte --with pillow --with wcwidth python3 make_real_catch.py <episode_dir> <out_dir> <repo>
"""
import json
import sys
from pathlib import Path

ep, out, repo = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo / "demo"))
import term_render as TR  # noqa: E402

COLS, ROWS = 92, 48
DIM, RED, BOLD, RST, CYAN, GREEN = "\x1b[2m", "\x1b[31;1m", "\x1b[1m", "\x1b[0m", "\x1b[36m", "\x1b[32m"
events = [json.loads(l) for l in (ep / "stream.jsonl").read_text().splitlines() if l.strip()]
prompt = (ep / "prompt.txt").read_text().rstrip("\n")
final = next(e for e in events if e["type"] == "result")["text"]

cast, t = [], 0.0


def emit(s, dt=0.0):
    global t
    t += dt
    cast.append([round(t, 3), "o", s.replace("\n", "\r\n")])


emit(f"{DIM}real model: Qwen3-4B · No Cap Arena task e05_word_count · strict mode · unedited output{RST}\n")
emit(f"{DIM}replayed from the episode's recorded stream; 87 s run shown in 10 s{RST}\n\n", 0.05)
emit(f"{BOLD}$ hermes chat -Q --oneshot --query-file prompt.txt{RST}\n", 0.3)
emit(prompt + "\n\n", 0.4)
for e in events:
    if e["type"] == "tool_use":
        args = " ".join(str(v) for v in e["input"].values())
        emit(f"{CYAN}● {e['name']}{RST}  {args}\n", 0.35)
    elif e["type"] == "tool_result" and e["name"] == "terminal":
        res = json.loads(e["output"])
        body = res["output"].rstrip("\n")
        lines = body.split("\n")
        for ln in lines:
            col = RED if ("failed" in ln or ln.startswith(("FAILED", "E "))) else ""
            emit(f"  {col}{ln}{RST if col else ''}\n", 0.05)
        emit(f"  {DIM}(exit {res['exit_code']}){RST}\n\n", 0.1)
emit("", 1.0)
reply, footer = final.split("\n\n🧢 Unverified:", 1)
for para in reply.split("\n\n"):
    emit(para + "\n\n", 0.5)
foot = "🧢 Unverified:" + footer
for ln in foot.split("\n"):
    col = RED if ln.startswith("🧢 CAP") else (BOLD if ln.startswith("Receipts") else "")
    emit(f"{col}{ln}{RST if col else ''}\n", 0.25)
emit("", 0.6)

head = {"version": 2, "width": COLS, "height": ROWS, "title": "No Cap: real Qwen3-4B catch (Arena e05_word_count)"}
cp = out / "real-catch.cast"
cp.write_text(json.dumps(head) + "\n" + "\n".join(json.dumps(c, ensure_ascii=False) for c in cast) + "\n",
              encoding="utf-8")
print("cast", cp, "t =", round(t, 2))

# GIF: term_render.gif, then a full-size poster of the last screen
TR.gif(cp, out / "real-catch.gif", step=0.25, max_hold=1.8, scale=0.75)
import pyte  # noqa: E402

screen = pyte.Screen(COLS, ROWS)
stream = pyte.ByteStream(screen)
for c in cast:
    stream.feed(c[2].encode("utf-8").replace(b"\xef\xb8\x8f", b""))
img = TR.Painter(15).paint(TR._runs(screen, COLS, ROWS), COLS)
img.save(out / "real-catch-poster.png", "PNG", optimize=True)
print("poster", img.size)
