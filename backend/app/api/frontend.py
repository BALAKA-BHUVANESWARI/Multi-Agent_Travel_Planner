"""Serving the built web app (frontend/dist). Both web servers use this."""
from __future__ import annotations

import os
from pathlib import Path

from app.core import config

CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".map": "application/json",
                 ".svg": "image/svg+xml", ".ico": "image/x-icon"}
NOT_BUILT = b"""<!doctype html><meta charset="utf-8"><title>ExecuTrip: Wish-to-Way</title>
<body style="font-family:system-ui;max-width:640px;margin:48px auto;padding:0 16px">
<h1>The web app is not built yet</h1>
<p>The API is running. To build the page, run these in the <code>frontend</code> folder, then reload:</p>
<pre>npm install
npm run build</pre></body>"""


def dist_dir() -> Path:
    override = os.environ.get("FRONTEND_DIST")
    return Path(override) if override else config.PROJECT_ROOT / "frontend" / "dist"


def asset(name: str) -> tuple[bytes, str] | None:
    """(bytes, content type) for a file of the built app, or None. Only plain file names directly inside dist/
    are served, so a request can never reach another folder."""
    name = name or "index.html"
    ctype = CONTENT_TYPES.get(Path(name).suffix)
    if not ctype or Path(name).name != name or name.startswith("."):
        return None
    path = dist_dir() / name
    if path.is_file():
        return path.read_bytes(), ctype
    return (NOT_BUILT, "text/html") if name == "index.html" else None
