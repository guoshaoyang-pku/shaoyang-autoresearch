#!/usr/bin/env python3
"""
Codex proxy — OpenAI Responses API (Codex CLI) <-> Chat Completions upstream.

Configure via environment variables or ``keys.json`` at the repository root
(sibling of this ``proxy/`` directory). See ``keys.example.json``.

Environment (highest priority):
  CODEX_PROXY_LISTEN_HOST     default 127.0.0.1
  CODEX_PROXY_LISTEN_PORT     default 4002
  CODEX_PROXY_UPSTREAM_URL    URL whose path is the prefix before /chat/completions
  CODEX_PROXY_API_KEY         sent as Bearer and api-key headers
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


def _keys_blob() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    p = os.path.join(root, "keys.json")
    if not os.path.isfile(p):
        return {}
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_runtime_config():
    keys = _keys_blob().get("codex_proxy") or {}
    if not isinstance(keys, dict):
        keys = {}

    listen_host = os.environ.get("CODEX_PROXY_LISTEN_HOST", keys.get("listen_host", "127.0.0.1"))
    listen_port = int(os.environ.get("CODEX_PROXY_LISTEN_PORT", keys.get("listen_port", 4002)))

    base_url = (os.environ.get("CODEX_PROXY_UPSTREAM_URL") or keys.get("upstream_base_url") or "").strip()
    if not base_url:
        base_url = "https://example.invalid/REPLACE_WITH_UPSTREAM_PREFIX"

    api_key = (os.environ.get("CODEX_PROXY_API_KEY") or keys.get("bearer_token") or "").strip()
    if not api_key:
        api_key = "REPLACE_WITH_UPSTREAM_API_KEY"

    fb = keys.get("fallback_models")
    if isinstance(fb, list) and fb:
        fallback_order = [str(x) for x in fb]
    else:
        fallback_order = [
            "gpt-5.5-2026-04-24",
            "gpt-5.4-2026-03-05",
            "gpt-5.3-codex-2026-02-24",
        ]

    default_model = str(keys.get("default_model") or fallback_order[0])

    ma = keys.get("model_aliases")
    if isinstance(ma, dict):
        model_aliases = {str(k): str(v) for k, v in ma.items()}
    else:
        model_aliases = {
            "gpt-5.5": "gpt-5.5-2026-04-24",
            "gpt-5.4": "gpt-5.4-2026-03-05",
            "gpt-5.3": "gpt-5.3-codex-2026-02-24",
        }

    parsed = urlparse(base_url)
    host = parsed.hostname or "example.invalid"
    base_path = (parsed.path or "").rstrip("/")
    scheme = (parsed.scheme or "https").lower()
    return (
        listen_host,
        listen_port,
        base_url,
        api_key,
        fallback_order,
        default_model,
        model_aliases,
        host,
        base_path,
        scheme,
    )


(
    LISTEN_HOST,
    LISTEN_PORT,
    BASE_URL,
    API_KEY,
    FALLBACK_ORDER,
    DEFAULT_MODEL,
    MODEL_ALIASES,
    _HOST,
    _BASE_PATH,
    _SCHEME,
) = _load_runtime_config()

EFFORT_CLAMP = {"xhigh": "high"}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name) if name else DEFAULT_MODEL


def clamp_effort(data: dict) -> dict:
    effort = (data.get("reasoning") or {}).get("effort") or data.get("reasoning_effort")
    if effort in EFFORT_CLAMP:
        mapped = EFFORT_CLAMP[effort]
        if isinstance(data.get("reasoning"), dict):
            data["reasoning"]["effort"] = mapped
        if "reasoning_effort" in data:
            data["reasoning_effort"] = mapped
    return data


def strip_encrypted(data: dict) -> dict:
    inc = data.get("include", [])
    if inc:
        data["include"] = [x for x in inc if "encrypted" not in str(x)]
        if not data["include"]:
            del data["include"]
    inp = data.get("input", [])
    if isinstance(inp, list):
        cleaned = []
        for item in inp:
            if not isinstance(item, dict):
                cleaned.append(item)
                continue
            if item.get("type") == "reasoning" and "encrypted_content" in item:
                continue
            item.pop("encrypted_content", None)
            cleaned.append(item)
        data["input"] = cleaned
    return data


def input_to_messages(inp) -> list:
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    messages = []
    for item in (inp or []):
        if not isinstance(item, dict):
            continue
        role = item.get("role", "user")
        content = item.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text"):
                    parts.append(part.get("text", ""))
            content = "".join(parts)
        messages.append({"role": role, "content": content})
    return messages


def responses_to_chat(data: dict) -> dict:
    messages = input_to_messages(data.get("input", []))
    system = data.get("instructions") or data.get("system")
    if system and not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {"role": "system", "content": system})

    req = {
        "model": data["model"],
        "messages": messages,
        "stream": data.get("stream", False),
    }
    max_tok = data.get("max_output_tokens")
    if max_tok:
        req["max_tokens"] = max_tok
    return req


def chat_to_responses(chat: dict, model: str, resp_id: str, msg_id: str) -> dict:
    choice = (chat.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    usage = chat.get("usage") or {}
    det = (usage.get("completion_tokens_details") or {})
    return {
        "id": resp_id,
        "object": "response",
        "created_at": chat.get("created", int(time.time())),
        "status": "completed",
        "model": chat.get("model", model),
        "output": [{
            "type": "message",
            "id": msg_id,
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
            "status": "completed",
        }],
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "output_tokens_details": {"reasoning_tokens": det.get("reasoning_tokens", 0)},
        },
    }


def sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def stream_chat_to_responses(resp, model: str, resp_id: str, msg_id: str):
    ts = int(time.time())
    actual_model = model
    accumulated = ""
    usage_info = None

    yield sse("response.created", {"type": "response.created", "response": {
        "id": resp_id, "object": "response", "created_at": ts,
        "status": "in_progress", "model": model, "output": [],
    }})
    yield sse("response.output_item.added", {"type": "response.output_item.added",
        "output_index": 0, "item": {
            "id": msg_id, "type": "message", "status": "in_progress",
            "role": "assistant", "content": [],
        }})
    yield sse("response.content_part.added", {"type": "response.content_part.added",
        "item_id": msg_id, "output_index": 0, "content_index": 0,
        "part": {"type": "output_text", "text": ""}})

    buf = b""
    while True:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                c = json.loads(data_str)
            except Exception:
                continue
            actual_model = c.get("model", actual_model)
            u = c.get("usage")
            if u:
                usage_info = u
            choices = c.get("choices") or []
            if not choices:
                continue
            delta_text = (choices[0].get("delta") or {}).get("content") or ""
            if delta_text:
                accumulated += delta_text
                yield sse("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "item_id": msg_id, "output_index": 0, "content_index": 0,
                    "delta": delta_text,
                })

    completed_item = {
        "id": msg_id, "type": "message", "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": accumulated}],
    }
    yield sse("response.output_text.done", {"type": "response.output_text.done",
        "item_id": msg_id, "output_index": 0, "content_index": 0, "text": accumulated})
    yield sse("response.output_item.done", {"type": "response.output_item.done",
        "output_index": 0, "item": completed_item})

    u = usage_info or {}
    det = (u.get("completion_tokens_details") or {})
    yield sse("response.completed", {"type": "response.completed", "response": {
        "id": resp_id, "object": "response", "created_at": ts,
        "status": "completed", "model": actual_model,
        "output": [completed_item],
        "usage": {
            "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
            "output_tokens_details": {"reasoning_tokens": det.get("reasoning_tokens", 0)},
        },
    }})


def build_conn():
    if _SCHEME == "http":
        return http.client.HTTPConnection(_HOST, timeout=180)
    ctx = ssl.create_default_context()
    return http.client.HTTPSConnection(_HOST, context=ctx, timeout=180)


def upstream_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "api-key": API_KEY,
    }


def is_model_error(status: int, body: bytes) -> bool:
    if status not in (400, 404, 422):
        return False
    try:
        msg = json.loads(body).get("error", {}).get("message", "").lower()
        return any(k in msg for k in ("not supported", "model", "invalid", "deployment", "does not exist"))
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[proxy] {fmt % args}", flush=True)

    def do_GET(self):
        b = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        try:
            data = json.loads(raw)
            data = strip_encrypted(data)
            data = clamp_effort(data)

            raw_model = data.get("model") or DEFAULT_MODEL
            data["model"] = resolve_model(raw_model)
            if data["model"] != raw_model:
                print(f"[proxy] model alias {raw_model!r} -> {data['model']!r}", flush=True)

            if not data.get("max_output_tokens"):
                data["max_output_tokens"] = 16000

            is_streaming = bool(data.get("stream"))
            primary_model = data["model"]
        except Exception as e:
            print(f"[proxy] parse error: {e}", flush=True)
            primary_model = DEFAULT_MODEL
            is_streaming = False

        try:
            chat_req = responses_to_chat(data)
        except Exception as e:
            print(f"[proxy] conversion error: {e}", flush=True)
            chat_req = {"model": primary_model, "messages": [{"role": "user", "content": ""}], "stream": is_streaming}

        resp_id = "resp_" + uuid.uuid4().hex[:20]
        msg_id = "msg_" + uuid.uuid4().hex[:16]
        chat_path = _BASE_PATH + "/chat/completions"

        print(f"[proxy] -> {self.path}  model={primary_model}  stream={is_streaming}", flush=True)

        try_models = [primary_model] + [m for m in FALLBACK_ORDER if m != primary_model]

        for model in try_models:
            chat_req["model"] = model
            req_body = json.dumps(chat_req).encode()
            try:
                conn = build_conn()
                conn.request("POST", chat_path, body=req_body, headers=upstream_headers())
                resp = conn.getresponse()
                print(f"[proxy] <- {resp.status}  model={model}", flush=True)

                if not is_streaming:
                    body = resp.read()
                    conn.close()
                    if is_model_error(resp.status, body):
                        print(f"[proxy] {model!r} rejected, trying fallback...", flush=True)
                        continue
                    if resp.status == 200:
                        try:
                            responses_body = json.dumps(
                                chat_to_responses(json.loads(body), model, resp_id, msg_id)
                            ).encode()
                        except Exception:
                            responses_body = body
                    else:
                        responses_body = body
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(responses_body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(responses_body)
                    return

                else:
                    peek = resp.read(512)
                    if is_model_error(resp.status, peek):
                        conn.close()
                        print(f"[proxy] {model!r} stream rejected, trying fallback...", flush=True)
                        continue

                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()

                    class _PeekedResp:
                        def __init__(self, r, prefix):
                            self._r = r
                            self._buf = prefix

                        def read(self, n):
                            if self._buf:
                                chunk = self._buf[:n]
                                self._buf = self._buf[n:]
                                return chunk
                            return self._r.read(n)

                    try:
                        for chunk in stream_chat_to_responses(_PeekedResp(resp, peek), model, resp_id, msg_id):
                            size = f"{len(chunk):X}\r\n".encode()
                            self.wfile.write(size + chunk + b"\r\n")
                            self.wfile.flush()
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except Exception as e:
                        print(f"[proxy] stream write error: {e}", flush=True)
                    finally:
                        conn.close()
                    return

            except Exception as e:
                print(f"[proxy] upstream error ({model}): {e}", flush=True)

        err = json.dumps({"error": {"message": "all models failed", "code": 502}}).encode()
        self.send_response(502)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(err)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(err)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print(f"[proxy] Codex proxy http://{LISTEN_HOST}:{LISTEN_PORT} -> {BASE_URL}", flush=True)
    print(f"[proxy] fallback: {FALLBACK_ORDER}", flush=True)
    Server((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()
