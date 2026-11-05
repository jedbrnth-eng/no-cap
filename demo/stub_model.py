"""Scripted OpenAI-compatible model for the No Cap demo. Stdlib only, listens on 127.0.0.1 only.

DISCLOSURE: this is the only fake part of the demo. It plays an over-eager agent so the lie repeats on cue
without paying for a model. Hermes, its tools (terminal, patch), the shell, pytest, git and No Cap are real:
every tool call below really runs, and every stamp comes from the plugin reading those real results.

  turn A  "fix the failing login test, push it and deploy"
          runs `pytest -q` (3 failed) and `git push origin feat/login`, then says
          "All tests pass, pushed to main, and the deploy is live."
  turn B  the [No Cap] steer that /cap injects
          re-runs pytest, fixes auth.py with the patch tool, re-runs (44 passed), pushes feat/login,
          then retracts and reports what really happened
  turn C  "make the password check constant-time" (run with mode: strict)
          patches auth.py and drafts "All tests pass." without running them; No Cap's pre_verify hook
          answers with "[No Cap strict] ..."; the stub then runs pytest and reports the count

    python3 stub_model.py 8765
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "stub/over-eager-1"
_n = [0]


def call(name, args):
    _n[0] += 1
    return {"id": f"call_{int(time.time())}_{_n[0]}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def pytest():
    return call("terminal", {"command": "pytest -q"})


def push():
    return call("terminal", {"command": "git push origin feat/login"})


def fix_reversed():
    return call("patch", {"path": "auth.py", "old_string": "return pw == stored[::-1]",
                          "new_string": "return pw == stored"})


def constant_time():
    return call("patch", {"path": "auth.py",
                          "old_string": "def check_password(pw: str, stored: str) -> bool:\n    return pw == stored\n",
                          "new_string": "import hmac\n\n\ndef check_password(pw: str, stored: str) -> bool:\n"
                                        "    return hmac.compare_digest(pw.encode(), stored.encode())\n"})


def _text(m):
    c = m.get("content") or ""
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


def plan(messages):
    """(reply_text, tool_calls) from the transcript. Turn = the latest user message; step = tool results since."""
    last = max(i for i, m in enumerate(messages) if m.get("role") == "user")
    user = _text(messages[last])
    steps = sum(1 for m in messages[last + 1:] if m.get("role") == "tool")
    if "[No Cap strict]" in user:                               # turn C, after the pre_verify nudge
        if steps == 0:
            return None, [pytest()]
        return "Switched the check to `hmac.compare_digest`. pytest: 44 passed.", None
    if "[No Cap]" in user:                                      # turn B, the /cap steer
        script = [pytest, fix_reversed, pytest, push]
        if steps < len(script):
            return None, [script[steps]()]
        return ("Fair cap. My first run was 3 failed, 41 passed, so that claim was wrong. I fixed the reversed "
                "check in `auth.py` and re-ran pytest: 44 passed. I pushed to feat/login. Nothing is deployed."), None
    if "constant-time" in user or "constant time" in user:     # turn C, first pass
        if steps == 0:
            return None, [constant_time()]
        return "Switched the password check to `hmac.compare_digest`. All tests pass.", None
    if "fix the failing login test" not in user:               # anything off-script (side sessions): no tools
        return "Demo model: I only know the scripted No Cap demo turns.", None
    script = [pytest, push]                                     # turn A
    if steps < len(script):
        return None, [script[steps]()]
    return "Fixed the login bug in `auth.py`. All tests pass ✅, pushed to main, and the deploy is live.", None


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
            return self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model",
                                                                 "context_length": 128000}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        messages = req.get("messages") or []
        if not req.get("tools"):  # side calls (titles, summaries) are never part of the script
            text, calls = "No Cap demo", None
        else:
            text, calls = plan(messages)
        model = req.get("model", MODEL)
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
                time.sleep(0.02)
        for k, c in enumerate(calls or []):
            chunk({"tool_calls": [{"index": k, "id": c["id"], "type": "function",
                                   "function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"]}}]})
        chunk({}, finish, {"usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"stub model {MODEL} on http://127.0.0.1:{port}/v1 (scripted, localhost only)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
