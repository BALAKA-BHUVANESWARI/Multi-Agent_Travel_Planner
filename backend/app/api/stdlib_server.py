"""A web server using only Python's standard library, with the same API and page as the FastAPI app.
Use it when FastAPI is not installed. From the backend folder:

    python -m app.api.stdlib_server --port 8000
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.api import frontend
from app.services.trip_service import ApiError, PlannerService

MAX_BODY_BYTES = 64 * 1024
API_PREFIX = "/api/v1"


def make_handler(service: PlannerService):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # quiet
            pass

        def _send(self, status: int, payload, ctype="application/json", retry_after=None):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if retry_after:
                self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            self.wfile.write(body)

        def _token(self) -> str | None:
            scheme, _, token = (self.headers.get("Authorization") or "").partition(" ")
            return (token.strip() or None) if scheme.lower() == "bearer" else None

        def _json_body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY_BYTES:
                raise ApiError(413, "request body too large")
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ApiError(400, "invalid JSON")

        def _route(self, method: str):
            path = self.path.split("?")[0].rstrip("/") or "/"
            if method == "GET" and not path.startswith("/api/"):
                found = frontend.asset(path[1:])
                if found is None:
                    raise ApiError(404, "not found")
                return 200, found[0], found[1]
            if not path.startswith(API_PREFIX + "/"):
                raise ApiError(404, "not found")
            path = path[len(API_PREFIX):]                      # routes below are relative to /api/v1
            if method == "GET" and path == "/health":
                return 200, service.health(), "application/json"
            token, client = self._token(), self.client_address[0]
            if method == "POST" and path == "/plan":
                body = self._json_body()
                return 200, service.plan(body.get("request"), body.get("group"), token, client), "application/json"
            m = re.fullmatch(r"/approve/([\w-]{1,64})", path)
            if method == "POST" and m:
                return 200, service.approve(m.group(1), self._json_body(), token, client), "application/json"
            m = re.fullmatch(r"/plan/([\w-]{1,64})", path)
            if method == "GET" and m:
                return 200, service.get(m.group(1), token, client), "application/json"
            m = re.fullmatch(r"/booking/([\w-]{1,64})/cancel", path)
            if method == "POST" and m:
                return 200, service.cancel_booking(m.group(1), self._json_body(), token, client), "application/json"
            if method == "POST" and path == "/explore":
                return 200, service.explore(self._json_body(), token, client), "application/json"
            if method == "POST" and path == "/emergency":
                return 200, service.emergency(self._json_body(), token, client), "application/json"
            m = re.fullmatch(r"/trip/([\w-]{1,64})/([a-z]{1,20})(?:/([\w-]{1,40}))?", path)
            if m and method in ("GET", "POST", "DELETE"):
                body = self._json_body() if method != "GET" else {}
                return 200, service.trip_tool(method, m.group(1), m.group(2), m.group(3), body, token,
                                              client), "application/json"
            if re.fullmatch(r"/(auth/(register|login|logout)|me(/memory)?|trips)", path):
                body = self._json_body() if method != "GET" else {}
                return 200, service.account(method, path[1:], body, token, client), "application/json"
            raise ApiError(404, "not found")

        def _handle(self, method: str):
            try:
                status, payload, ctype = self._route(method)
                self._send(status, payload, ctype)
            except ApiError as e:
                self._send(e.status, {"error": e.message}, retry_after=e.retry_after)
            except Exception as e:           # noqa: BLE001
                self._send(500, {"error": f"internal error: {type(e).__name__}"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

    return Handler


def serve(service: PlannerService, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service))


def main() -> None:
    from app.core import config
    from app.core.rate_limit import RateLimiter
    from app.graph.engine import make_planner
    config.load_env()
    ap = argparse.ArgumentParser(description="Travel planner dev server (stdlib)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--engine", default=None, help="auto | langgraph | runner")
    args = ap.parse_args()
    service = PlannerService(make_planner(args.engine),
                             limiter=RateLimiter() if config.rate_limits_enabled() else None)
    srv = serve(service, args.host, args.port)
    print(f"Travel planner ({service.engine} engine) on http://{args.host}:{args.port}  - Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
