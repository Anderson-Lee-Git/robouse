"""Scripted local stand-ins for model APIs, for checking the plumbing of model routes and harnesses without a key or a
request to a provider. Standard library only. Two wire formats, one scripted "model":

  gemini   the Gemini API's generateContent and streamGenerateContent (gemini/ models through LiteLLM's Gemini route,
           and Gemini CLI)
  chat     OpenAI-compatible chat completions, streamed or not (openrouter/ models, through LiteLLM's openai/ route)

The scripted model plays one short episode with whatever tools the request offers: it runs the shell tool
(`robo observe --image`, then lists the saved camera images), reads the first image with the file-reading tool if there
is one, ends the episode with `robo done`, and finishes (mini-swe-agent, whose one tool is `bash`, ends on a command
that prints COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT). Like Gemini 3 and later, the gemini stand-in puts a thought
signature on every function call and refuses a request whose function calls in the current turn lack the signature it
issued (HTTP 400, as the Gemini API answers); `--lenient` only records that. The key is never logged, only where it
came from.

One JSON line per request goes to --log: the call, the tools offered, the thinking config, where the request's images
were (inside a function response, as an inline or image part of a user message, in a tool message, or as base64 text,
which a model cannot see as an image) and, for gemini, whether every signature came back.

  python -I tests/model_standin.py --api gemini --port 8790 --log requests.jsonl [--probe 'env | sort'] [--dump FILE]
  GEMINI_API_BASE=http://127.0.0.1:8790/v1beta                 (LiteLLM's gemini/ route: the model gateway)
  GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8790                 (Gemini CLI)
  python -I tests/model_standin.py --api chat --port 8791 --log requests.jsonl
  BENCHFLOW_PROVIDER_BASE_URL=http://127.0.0.1:8791/api/v1    (BenchFlow's route for a registry provider, e.g. openrouter)
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

SHELL_TOOLS = ("run_shell_command", "Bash", "bash", "shell")
READ_TOOLS = {"read_file": "file_path", "Read": "file_path", "read": "path"}  # tool name: its path argument
OBSERVE = 'robo observe --image && ls -d "$PWD"/observations/*.png'
SUBMIT = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
PATH_RE = re.compile(r"(/[^\s\"']+?/observations/[^\s\"']+?\.png)")
GEMINI_CALL_RE = re.compile(r"^/v1(?:alpha|beta)?/models/([^/:]+):(generateContent|streamGenerateContent|countTokens)$")
MISSING = (
    "Function call is missing a thought_signature in functionCall parts. This is required for tools to work "
    "correctly, and missing thought_signature may lead to degraded model performance."
)


def signature(step: int) -> str:
    return base64.b64encode(f"standin-signature-{step}".encode()).decode()


def policy(calls: list[tuple[str, dict]], outputs: str, tools: list[str], probe: str = "") -> tuple[str, Any]:
    """The scripted model's next action from the whole conversation so far: ("call", (tool, args)) or ("text", str).
    `calls`: every tool call made, in order; `outputs`: the tool results' text."""
    shell = next((t for t in SHELL_TOOLS if t in tools), None)
    read = next((t for t in READ_TOOLS if t in tools), None)
    made = json.dumps(calls)
    if shell is None:
        return "text", "No shell tool was offered."
    if "robo done" in made:
        if tools == ["bash"] and SUBMIT not in made:
            return "call", ("bash", {"command": f"echo {SUBMIT}"})
        return "text", "Done."
    if probe and not any(args.get("command") == probe for _, args in calls):
        return "call", (shell, {"command": probe})
    if "robo observe" not in made:
        return "call", (shell, {"command": OBSERVE})
    image = PATH_RE.search(outputs)
    if read and not any(name == read for name, _ in calls) and image:
        return "call", (read, {READ_TOOLS[read]: image.group(1)})
    return "call", (shell, {"command": 'robo done "stand-in"'})


def _text_images(value: Any) -> int:
    """Images sent as text: data URIs, or bare base64 PNGs."""
    s = json.dumps(value)
    return s.count("data:image/") + s.count("iVBORw0KGgo") - s.count("base64,iVBORw0KGgo")


# ---- the Gemini API -------------------------------------------------------------------------------------------------


def _parts(content: Any) -> list[dict]:
    return [p for p in (content or {}).get("parts") or [] if isinstance(p, dict)]


def _call_of(part: dict) -> dict | None:
    return part.get("functionCall") or part.get("function_call")


def _response_of(part: dict) -> dict | None:
    return part.get("functionResponse") or part.get("function_response")


def current_turn(contents: list) -> list[dict]:
    """The contents after the last user message that holds text: the model's steps of this turn and their results."""
    start = 0
    for i, c in enumerate(contents):
        if isinstance(c, dict) and c.get("role", "user") == "user":
            ps = _parts(c)
            if any("text" in p and not p.get("thought") for p in ps) and not any(_response_of(p) for p in ps):
                start = i + 1
    return [c for c in contents[start:] if isinstance(c, dict)]


def check_signatures(turn: list[dict]) -> str:
    """'ok' when the first function call of every model step in the turn carries the signature issued for it, else
    'missing' or 'wrong'."""
    step = 0
    for c in turn:
        calls = [p for p in _parts(c) if _call_of(p)]
        if c.get("role") != "model" or not calls:
            continue
        got = calls[0].get("thoughtSignature") or calls[0].get("thought_signature")
        if not got:
            return "missing"
        if got != signature(step):
            return "wrong"
        step += 1
    return "ok"


def gemini_images(contents: list) -> dict[str, int]:
    """Where the request's images are: inside a function response, as inline parts, or as base64 text."""
    out = {"function_response": 0, "inline": 0, "as_text": 0}
    for c in contents:
        for p in _parts(c):
            if p.get("inlineData") or p.get("inline_data"):
                out["inline"] += 1
            if (r := _response_of(p)) is not None:
                inner = [q for q in r.get("parts") or [] if isinstance(q, dict)]
                out["function_response"] += sum(1 for q in inner if q.get("inlineData") or q.get("inline_data"))
                out["as_text"] += _text_images(r.get("response"))
            if isinstance(p.get("text"), str):
                out["as_text"] += _text_images(p["text"])
    return out


def gemini_answer(body: dict, model: str, probe: str, lenient: bool) -> tuple[int, dict, dict]:
    """(HTTP status, the whole response or the error, the log record) for one generateContent request."""
    contents = body.get("contents") or []
    tools = [
        str(d.get("name"))
        for t in body.get("tools") or []
        for d in (t.get("functionDeclarations") or t.get("function_declarations") or [])
    ]
    turn = current_turn(contents)
    step = sum(1 for c in turn if c.get("role") == "model" and any(_call_of(p) for p in _parts(c)))
    cfg = body.get("generationConfig") or body.get("generation_config") or {}
    rec = {
        "step": step,
        "tools": tools,
        "thinking_config": cfg.get("thinkingConfig") or cfg.get("thinking_config"),
        "images": gemini_images(contents),
        "signatures": check_signatures(turn),
    }
    if rec["signatures"] != "ok" and not lenient:
        rec["answer"] = 400
        return 400, {"error": {"code": 400, "message": MISSING, "status": "INVALID_ARGUMENT"}}, rec
    calls = [
        (str(call.get("name")), call.get("args") or {})
        for c in contents
        if isinstance(c, dict) and c.get("role") == "model"
        for p in _parts(c)
        if (call := _call_of(p))
    ]
    outputs = json.dumps([_response_of(p) for c in contents for p in _parts(c) if _response_of(p)])
    kind, what = policy(calls, outputs.replace("\\n", "\n"), tools, probe)
    part: dict = (
        {"functionCall": {"name": what[0], "args": what[1]}, "thoughtSignature": signature(step)}
        if kind == "call"
        else {"text": what}
    )
    rec["answer"] = what[0] if kind == "call" else "text"
    usage = {"promptTokenCount": 1000 + 100 * step, "candidatesTokenCount": 25, "thoughtsTokenCount": 40}
    usage["totalTokenCount"] = sum(usage.values())
    return 200, {"part": part, "usage": usage, "model": model}, rec


# ---- OpenAI-compatible chat completions -----------------------------------------------------------------------------


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content or "")


def chat_images(messages: list) -> dict[str, int]:
    """Where the request's images are: image parts of user messages, image parts of tool messages, or base64 text
    (a data URI as a tool message's text, which LiteLLM sends for the lone image of an Anthropic tool_result)."""
    out = {"user_parts": 0, "tool_parts": 0, "as_text": 0}
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        parts = [p for p in content if isinstance(p, dict)] if isinstance(content, list) else []
        images = sum(1 for p in parts if p.get("type") in ("image_url", "input_image", "image"))
        if m.get("role") == "user":
            out["user_parts"] += images
        elif m.get("role") == "tool":
            out["tool_parts"] += images
        out["as_text"] += _text_images(content if isinstance(content, str) else [p.get("text") for p in parts])
    return out


def chat_answer(body: dict, probe: str) -> tuple[dict, dict]:
    """(the assistant message with its usage, the log record) for one chat completions request."""
    messages = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    tools = [str((t.get("function") or {}).get("name")) for t in body.get("tools") or [] if isinstance(t, dict)]
    calls = []
    for m in messages:
        for tc in m.get("tool_calls") or [] if m.get("role") == "assistant" else []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"raw": fn.get("arguments")}
            calls.append((str(fn.get("name")), args))
    outputs = "\n".join(_text_of(m.get("content")) for m in messages if m.get("role") == "tool")
    kind, what = policy(calls, outputs, tools, probe)
    rec = {"tools": tools, "images": chat_images(messages), "answer": what[0] if kind == "call" else "text"}
    if kind == "call":
        call = {"id": f"call_{len(calls)}", "type": "function"}
        call["function"] = {"name": what[0], "arguments": json.dumps(what[1])}
        msg: dict = {"role": "assistant", "content": None, "tool_calls": [call]}
    else:
        msg = {"role": "assistant", "content": what}
    usage = {"prompt_tokens": 1000 + 100 * len(calls), "completion_tokens": 25, "total_tokens": 1025 + 100 * len(calls)}
    return {"message": msg, "finish": "tool_calls" if kind == "call" else "stop", "usage": usage}, rec


# ---- the server -----------------------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    api = "gemini"
    log_path: str | None = None
    dump_path: str | None = None  # whole request bodies (prompts and images included), for debugging
    lenient = False
    probe = ""
    lock = threading.Lock()
    records: list[dict] = []

    def log_message(self, *a) -> None:
        pass

    def _send(self, code: int, obj: Any) -> None:
        out = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _sse(self, events: list[Any], done: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ev in events:
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
        if done:
            self.wfile.write(b"data: [DONE]\n\n")

    def _record(self, rec: dict) -> None:
        with Handler.lock:
            Handler.records.append(rec)
            if Handler.log_path:
                with open(Handler.log_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")

    def do_GET(self) -> None:
        self._record({"path": urlparse(self.path).path, "method": "GET"})
        self._send(404, {"error": {"code": 404, "message": "not served by the stand-in"}})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if Handler.dump_path:
            with Handler.lock, open(Handler.dump_path, "a") as f:
                f.write(json.dumps({"path": url.path, "body": body}) + "\n")
        if Handler.api == "chat":
            return self._chat(url, body)
        auth = "header" if self.headers.get("x-goog-api-key") else "query" if "key" in parse_qs(url.query) else "none"
        m = GEMINI_CALL_RE.match(url.path)
        if not m:
            self._record({"path": url.path, "method": "POST", "auth": auth})
            return self._send(404, {"error": {"code": 404, "message": "not served by the stand-in"}})
        model, method = m.groups()
        if method == "countTokens":
            self._record({"path": url.path, "call": method, "model": model, "auth": auth})
            return self._send(200, {"totalTokens": 100 * len(body.get("contents") or [])})
        code, out, rec = gemini_answer(body, model, Handler.probe, Handler.lenient)
        self._record({"path": url.path, "call": method, "model": model, "auth": auth, **rec})
        if code != 200:
            return self._send(code, out)
        thought = {"text": "Planning the next step.", "thought": True}
        head = {"candidates": [{"content": {"role": "model", "parts": [thought]}, "index": 0}], "modelVersion": model}
        tail = {
            "candidates": [{"content": {"role": "model", "parts": [out["part"]]}, "finishReason": "STOP", "index": 0}],
            "usageMetadata": out["usage"],
            "modelVersion": model,
        }
        if method == "generateContent":
            tail["candidates"][0]["content"]["parts"] = [thought, out["part"]]
            return self._send(200, tail)
        if "sse" in parse_qs(url.query).get("alt", []):
            return self._sse([head, tail])
        self._send(200, [head, tail])

    def _chat(self, url, body: dict) -> None:
        if not url.path.endswith("/chat/completions"):
            self._record({"path": url.path, "method": "POST"})
            return self._send(404, {"error": {"code": 404, "message": "not served by the stand-in"}})
        out, rec = chat_answer(body, Handler.probe)
        auth = "bearer" if self.headers.get("Authorization", "").startswith("Bearer ") else "none"
        self._record(
            {"path": url.path, "model": body.get("model"), "auth": auth, "stream": bool(body.get("stream")), **rec}
        )
        base = {"id": "chatcmpl-standin", "created": 0, "model": str(body.get("model"))}
        if not body.get("stream"):
            choice = {"index": 0, "message": out["message"], "finish_reason": out["finish"]}
            return self._send(200, {**base, "object": "chat.completion", "choices": [choice], "usage": out["usage"]})
        msg = out["message"]
        delta: dict = {"role": "assistant"}
        if msg.get("tool_calls"):
            delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
        else:
            delta["content"] = msg["content"]
        chunk = {**base, "object": "chat.completion.chunk"}
        self._sse(
            [
                {**chunk, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {
                    **chunk,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": out["finish"]}],
                    "usage": out["usage"],
                },
            ],
            done=True,
        )


def serve(
    api: str = "gemini",
    port: int = 0,
    log: str | None = None,
    lenient: bool = False,
    probe: str = "",
    dump: str | None = None,
) -> ThreadingHTTPServer:
    """Start a stand-in on 127.0.0.1 in a daemon thread; its URL is http://127.0.0.1:<server_address[1]>."""
    Handler.api, Handler.log_path, Handler.lenient, Handler.probe, Handler.dump_path = api, log, lenient, probe, dump
    Handler.records = []
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", choices=("gemini", "chat"), default="gemini")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--log", help="JSON lines, one per request")
    ap.add_argument("--lenient", action="store_true", help="answer requests whose thought signatures are missing")
    ap.add_argument("--probe", default="", help="a shell command the scripted model runs first")
    ap.add_argument("--dump", help="JSON lines, each request's whole body (prompts and images included)")
    a = ap.parse_args()
    srv = serve(a.api, a.port, a.log, a.lenient, a.probe, a.dump)
    print(f"http://127.0.0.1:{srv.server_address[1]}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
