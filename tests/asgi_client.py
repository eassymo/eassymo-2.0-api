"""Minimal ASGI client for route tests (httpx, which TestClient needs, is not installed)."""
import asyncio
import json as _json
from types import SimpleNamespace
from urllib.parse import urlsplit


class AsgiClient:
    def __init__(self, app):
        self.app = app

    def request(self, method, url, headers=None, json=None):
        parts = urlsplit(url)
        body = b"" if json is None else _json.dumps(json).encode()
        raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        if json is not None:
            raw_headers.append((b"content-type", b"application/json"))
        captured = {"status": None, "body": b""}
        sent = False
        done = None

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await done.wait()  # disconnect only after the response is complete
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
            elif message["type"] == "http.response.body":
                captured["body"] += message.get("body", b"")
                if not message.get("more_body"):
                    done.set()

        scope = {
            "type": "http", "asgi": {"spec_version": "2.3", "version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": parts.path, "raw_path": parts.path.encode(),
            "query_string": parts.query.encode(), "headers": raw_headers,
            "client": ("10.0.0.8", 443), "server": ("testserver", 80),
        }
        async def run():
            nonlocal done
            done = asyncio.Event()
            await self.app(scope, receive, send)

        asyncio.run(run())
        raw = captured["body"]
        return SimpleNamespace(
            status_code=captured["status"],
            text=raw.decode(errors="replace"),
            json=lambda: _json.loads(raw or b"null"),
        )

    def get(self, url, headers=None):
        return self.request("GET", url, headers=headers)

    def post(self, url, json=None, headers=None):
        return self.request("POST", url, headers=headers, json=json)
