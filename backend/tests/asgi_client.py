"""A minimal client that calls the app as a server would (ASGI), with the standard library only: no test client
dependency. It keeps the cookies the app sets, like a browser, so a sign-in carries over to the next call. The app's
lifespan (heartbeat, startup reconciliation) is not run; background tasks run before the call returns."""
import asyncio
import json
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from urllib.parse import urlsplit


@dataclass
class Answer:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body or b"null")

    @property
    def message(self) -> str:
        detail = (self.json() or {}).get("detail") if self.body else None
        return detail[0]["message"] if isinstance(detail, list) and detail else str(detail)

    @property
    def code(self) -> str | None:
        detail = (self.json() or {}).get("detail") if self.body else None
        return detail[0].get("code") if isinstance(detail, list) and detail else None


@dataclass
class Client:
    app: object
    cookies: dict = field(default_factory=dict)

    def request(self, method: str, url: str, json_body=None, headers: dict | None = None) -> Answer:
        parts = urlsplit(url)
        body = b"" if json_body is None else json.dumps(json_body, default=str).encode()
        raw_headers = [(b"host", b"testserver")]
        if body:
            raw_headers.append((b"content-type", b"application/json"))
        if self.cookies:
            raw_headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode()))
        for name, value in (headers or {}).items():
            raw_headers.append((name.lower().encode(), str(value).encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(),
                 "scheme": "http", "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
                 "root_path": "", "headers": raw_headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
        sent = {"body": b"", "status": 0, "headers": []}
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                sent["status"] = message["status"]
                sent["headers"] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                sent["body"] += message.get("body", b"")

        asyncio.run(self.app(scope, receive, send))
        headers_out: dict = {}
        for name, value in sent["headers"]:
            key, text = name.decode().lower(), value.decode()
            headers_out.setdefault(key, []).append(text)
            if key == "set-cookie":
                cookie = SimpleCookie()
                cookie.load(text)
                for morsel in cookie.values():
                    if morsel["max-age"] == "0" or (morsel["expires"] and "1970" in morsel["expires"]) or morsel.value == "":
                        self.cookies.pop(morsel.key, None)
                    else:
                        self.cookies[morsel.key] = morsel.value
        return Answer(sent["status"], headers_out, sent["body"])

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, json_body=None, **kw):
        return self.request("POST", url, json_body, **kw)

    def put(self, url, json_body=None, **kw):
        return self.request("PUT", url, json_body, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)
