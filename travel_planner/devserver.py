"""Stdlib HTTP server exposing the same API as the FastAPI app (no extra dependencies).

    python -m travel_planner.devserver --port 8000
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import ApiError, PlannerService

STATIC = Path(__file__).parent / "static"
MAX_BODY_BYTES = 64 * 1024


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
            if method == "GET" and path == "/":
                return 200, (STATIC / "index.html").read_bytes(), "text/html"
            if method == "GET" and path == "/api/health":
                return 200, service.health(), "application/json"
            token, client = self._token(), self.client_address[0]
            if method == "POST" and path == "/api/plan":
                body = self._json_body()
                return 200, service.plan(body.get("request"), body.get("group"), token, client), "application/json"
            m = re.fullmatch(r"/api/approve/([\w-]{1,64})", path)
            if method == "POST" and m:
                return 200, service.approve(m.group(1), self._json_body(), token, client), "application/json"
            m = re.fullmatch(r"/api/plan/([\w-]{1,64})", path)
            if method == "GET" and m:
                return 200, service.get(m.group(1), token, client), "application/json"
            m = re.fullmatch(r"/api/booking/([\w-]{1,64})/cancel", path)
            if method == "POST" and m:
                return 200, service.cancel_booking(m.group(1), self._json_body(), token, client), "application/json"
            if method == "POST" and path == "/api/emergency":
                return 200, service.emergency(self._json_body(), token, client), "application/json"
            m = re.fullmatch(r"/api/trip/([\w-]{1,64})/([a-z]{1,20})(?:/([\w-]{1,40}))?", path)
            if m and method in ("GET", "POST", "DELETE"):
                body = self._json_body() if method != "GET" else {}
                return 200, service.trip_tool(method, m.group(1), m.group(2), m.group(3), body, token,
                                              client), "application/json"
            if re.fullmatch(r"/api/(auth/(register|login|logout)|me(/memory)?|trips)", path):
                body = self._json_body() if method != "GET" else {}
                return 200, service.account(method, path[len("/api/"):], body, token, client), "application/json"
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
    from . import config
    from .engine import make_planner
    from .ratelimit import RateLimiter
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
