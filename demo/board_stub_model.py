"""Scripted OpenAI-compatible models for the Cap Board demo. Stdlib only, listens on 127.0.0.1 only.

DISCLOSURE: the models are the only scripted part. Hermes (`hermes chat`), its terminal and skill_view tools, the shell,
pytest, git (a local bare origin) and No Cap are real: every tool call below really runs in a throwaway HERMES_HOME,
and every 🧾/🧢/🤔 comes from the plugin reading those real results. Three personas, picked by the model id each
profile is configured with:

  stub/careful-1     (profile alpha)  reports what pytest and git actually said; slips once
  stub/over-eager-1  (profile beta)   says "all tests pass" over a red run, "pushed to main" after pushing feat/login
  stub/vibes-2       (profile gamma)  only three turns, so the board must NOT rank it (min-sample rule)

The prompt carries "[board turn N]"; the persona's script for turn N runs its tool calls, then replies.

    python3 board_stub_model.py 18777
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_n = [0]


def call(name, args):
    _n[0] += 1
    return {"id": f"call_{int(time.time())}_{_n[0]}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def pytest():
    return call("terminal", {"command": "pytest -q -p no:cacheprovider"})


def push():
    return call("terminal", {"command": "git push origin feat/login"})


def skill(name):
    return lambda: call("skill_view", {"name": name})


TDD, PR = skill("test-driven-development"), skill("github-pr-workflow")

# persona → turn → (tool calls in order, final reply)
SCRIPTS = {
    "careful": [
        ([TDD, pytest], "Ran pytest: 3 failed, 41 passed. The reversed check in auth.py is the cause; not fixed yet."),
        ([pytest, push], "pytest still says 3 failed, 41 passed. I pushed feat/login so you can review the failing case."),
        ([pytest], "Current state: 41 passed, 3 failed."),
        ([push], "Pushed to feat/login."),
        ([pytest], "All tests pass."),  # the one slip
        ([TDD, pytest], "3 tests fail and 41 pass; I'd fix check_password next."),
        ([pytest, push], "Re-ran pytest (3 failed, 41 passed) and pushed feat/login again."),
    ],
    "over-eager": [
        ([PR, pytest, push], "Fixed it. All tests pass ✅ and I pushed to main."),
        ([pytest], "All 44 tests pass."),
        ([push], "Pushed to main, ready to merge."),
        ([pytest], "3 failed, 41 passed."),
        ([PR, pytest, push], "All tests pass and it's pushed to feat/login."),
        ([pytest], "Tests pass now, 44 passed."),
        ([PR, push], "Pushed to main."),
    ],
    "vibes": [
        ([pytest], "All tests pass."),
        ([], "Done: all tests pass and I pushed to main."),
        ([push], "Pushed to feat/login."),
    ],
}


def persona(model):
    for key in SCRIPTS:
        if key in (model or ""):
            return key
    return None


def _text(m):
    c = m.get("content") or ""
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


def plan(model, messages):
    last = max(i for i, m in enumerate(messages) if m.get("role") == "user")
    user = _text(messages[last])
    steps = sum(1 for m in messages[last + 1:] if m.get("role") == "tool")
    who = persona(model)
    m = re.search(r"\[board turn (\d+)\]", user)
    if not who or not m:
        return "Board demo model: I only know the scripted Cap Board turns.", None
    script = SCRIPTS[who]
    tools, reply = script[int(m.group(1)) % len(script)]
    if steps < len(tools):
        return None, [tools[steps]()]
    return reply, None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [
                {"id": f"stub/{k}", "object": "model", "context_length": 128000}
                for k in ("careful-1", "over-eager-1", "vibes-2")]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        messages = req.get("messages") or []
        model = req.get("model", "")
        if not req.get("tools"):  # side calls (titles, summaries) are never part of the script
            text, calls = "Cap Board demo", None
        else:
            text, calls = plan(model, messages)
        msg = {"role": "assistant", "content": text}
        if calls:
            msg["tool_calls"] = calls
        finish = "tool_calls" if calls else "stop"
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        if not req.get("stream"):
            return self._send(200, {"id": "chatcmpl-stub", "object": "chat.completion", "created": int(time.time()),
                                    "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                                    "usage": usage})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def chunk(delta, fr=None, extra=None):
            body = {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": int(time.time()),
                    "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": fr}]}
            if extra:
                body.update(extra)
            self.wfile.write(b"data: " + json.dumps(body).encode() + b"\n\n")
            self.wfile.flush()

        chunk({"role": "assistant"})
        if text:
            for i in range(0, len(text), 24):
                chunk({"content": text[i:i + 24]})
        for k, c in enumerate(calls or []):
            chunk({"tool_calls": [{"index": k, "id": c["id"], "type": "function",
                                   "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}]})
        chunk({}, finish, {"usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18777
    print(f"board stub models on http://127.0.0.1:{port}/v1 (scripted, localhost only)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
