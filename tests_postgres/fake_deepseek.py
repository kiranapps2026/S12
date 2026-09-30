"""A local stand-in for api.deepseek.com/chat/completions with scripted behaviours.

The REAL DeepSeekIntentModel talks to it over REAL HTTP, so status codes, timeouts, bodies and
headers are exercised for real; only the provider's answers are simulated. Behaviour is chosen by
a marker at the start of the user's text: "[[empty]] delete the contact", "[[429]] ...", etc.
Without a marker it answers like a well-behaved model (keyword -> intent, "xN" -> N items).
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARKER = re.compile(r"^\[\[([a-z0-9\-]+)\]\]\s*")


def _answer(text: str, intents: list[str]) -> str:
    low = text.lower()
    intent = ("contact.delete" if "delete" in low else "contact.create" if "create" in low
              else "contact.list" if "contact" in low or "list" in low else "unknown")
    if intent not in intents and intent != "unknown":
        intent = "unknown"
    m = re.search(r"\bx(\d+)\b", low)
    params = {"items": [{} for _ in range(int(m.group(1)))]} if m else {}
    return json.dumps({"intent": intent, "confidence": 0.2 if intent == "unknown" else 0.95,
                       "parameters": params})


class FakeDeepSeek:
    def __init__(self, delay: float = 0.0) -> None:
        self.requests: list[dict] = []          # every request body received (parsed)
        self.auth_headers: list[str] = []
        self.delay = delay
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # quiet
                pass

            def do_POST(self):                  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with outer._lock:
                    outer.requests.append(body)
                    outer.auth_headers.append(self.headers.get("Authorization", ""))
                if outer.delay:
                    time.sleep(outer.delay)
                text = body["messages"][1]["content"]
                system = body["messages"][0]["content"]
                intents = re.search(r"Allowed intent values: (.*)", system).group(1).split(", ")
                m = MARKER.match(text)
                mode, plain = (m.group(1), MARKER.sub("", text)) if m else ("ok", text)
                with outer._lock:
                    outer._seen[text] = outer._seen.get(text, 0) + 1
                    nth = outer._seen[text]
                self._respond(mode, plain, intents, nth)

            def _send(self, code, payload, raw=False):
                data = payload.encode() if raw else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _choice(self, content, finish="stop"):
                return {"model": "deepseek-flash", "usage": {"total_tokens": 100},
                        "choices": [{"index": 0, "finish_reason": finish,
                                     "message": {"role": "assistant", "content": content}}]}

            def _respond(self, mode, plain, intents, nth):
                ok = _answer(plain, intents)
                if mode == "ok":
                    return self._send(200, self._choice(ok))
                if mode == "empty":
                    return self._send(200, self._choice(""))
                if mode == "empty-once":               # empty first time, fine on the retry
                    return self._send(200, self._choice("" if nth == 1 else ok))
                if mode == "trunc":
                    return self._send(200, self._choice(ok[: len(ok) // 2], "length"))
                if mode == "trunc-once":
                    return self._send(200, self._choice(ok[: len(ok) // 2] if nth == 1 else ok,
                                                        "length" if nth == 1 else "stop"))
                if mode == "notjson":
                    return self._send(200, self._choice("Sure! Here is your answer: contact.list"))
                if mode == "wrongintent":
                    return self._send(200, self._choice(json.dumps(
                        {"intent": "contact.destroy_all", "confidence": 0.99, "parameters": {}})))
                if mode == "badconf":
                    return self._send(200, self._choice(json.dumps(
                        {"intent": "contact.list", "confidence": "very", "parameters": {}})))
                if mode == "filter":
                    return self._send(200, self._choice("", "content_filter"))
                if mode in ("429", "402", "401", "500", "503"):
                    return self._send(int(mode), {"error": {"message": f"simulated {mode}",
                                                            "type": "simulated"}})
                if mode == "garbage":
                    return self._send(200, "<html>gateway error</html>", raw=True)
                if mode == "nochoices":
                    return self._send(200, {"model": "deepseek-flash", "usage": {"total_tokens": 1},
                                            "choices": []})
                if mode == "slow":
                    time.sleep(5)
                    return self._send(200, self._choice(ok))
                return self._send(200, self._choice(ok))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/chat/completions"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    def calls_for(self, text_fragment: str) -> int:
        return sum(1 for r in self.requests if text_fragment in r["messages"][1]["content"])
