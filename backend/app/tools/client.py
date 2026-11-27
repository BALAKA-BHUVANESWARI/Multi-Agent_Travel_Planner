"""Tool clients: in-process (default, used by tests) and MCP (stdio).

Both expose ``call(name, **kwargs) -> dict`` and raise ``ToolError`` on failure.
``call_with_retry`` adds exponential backoff for retryable errors.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from typing import Callable

from app.core import config
from app.observability import recorder as observe
from app.tools.errors import ToolError
from app.tools.registry import TOOLS


class InProcessClient:
    """Direct function calls. Supports latency + failure injection for tests."""

    def __init__(self, latency: float = 0.0, failures: dict | None = None):
        self.latency = latency
        self.failures = dict(failures or {})     # tool -> N (fail first N calls) or -1 (always)
        self.calls: list[dict] = []              # timeline: name, start, end, ok
        self._lock = threading.Lock()
        self._count: dict[str, int] = {}

    def call(self, name: str, **kwargs) -> dict:
        t0 = time.perf_counter()
        ok = False
        try:
            with self._lock:
                n = self._count.get(name, 0)
                self._count[name] = n + 1
            if self.latency:
                time.sleep(self.latency)
            limit = self.failures.get(name, 0)
            if limit == -1 or n < limit:
                raise ToolError(f"simulated outage in {name}", retryable=True)
            fn = TOOLS.get(name)
            if fn is None:
                raise ToolError(f"unknown tool '{name}'", retryable=False)
            try:
                result = fn(**kwargs)
            except ToolError:
                raise
            except TypeError as e:
                raise ToolError(f"bad arguments for {name}: {e}", retryable=False)
            ok = True
            return result
        finally:
            with self._lock:
                self.calls.append({"name": name, "start": t0, "end": time.perf_counter(), "ok": ok})

    def call_count(self, name: str) -> int:
        return self._count.get(name, 0)

    def close(self) -> None:
        pass


class McpClient:
    """Calls the tools through the MCP stdio server (app.tools.mcp_server)."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._session = None
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise ToolError("MCP server did not start in time", retryable=False)
        if self._error:
            raise ToolError(f"MCP server failed to start: {self._error}", retryable=False)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        self._stop = asyncio.Event()
        pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env = dict(os.environ)
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.tools.mcp_server"], env=env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except Exception as e:                 # startup/transport failure
            self._error = e
            self._ready.set()

    async def _call(self, name: str, kwargs: dict) -> dict:
        res = await self._session.call_tool(name, kwargs)
        text = "".join(getattr(c, "text", "") for c in res.content)
        is_error = getattr(res, "is_error", None)
        if is_error is None:
            is_error = getattr(res, "isError", False)
        if is_error:
            raise ToolError(text or f"MCP tool {name} failed", retryable="unsupported" not in text
                            and "unknown" not in text and "invalid" not in text
                            and "same" not in text and "must be" not in text)
        structured = getattr(res, "structured_content", None)
        if structured is None:
            structured = getattr(res, "structuredContent", None)
        if isinstance(structured, dict) and structured:
            data = structured.get("result", structured) if set(structured) == {"result"} else structured
        else:
            data = json.loads(text)
        if isinstance(data, dict) and set(data) == {"error", "retryable"}:
            raise ToolError(str(data["error"]), retryable=bool(data["retryable"]))
        return data

    def call(self, name: str, **kwargs) -> dict:
        fut = asyncio.run_coroutine_threadsafe(self._call(name, kwargs), self._loop)
        try:
            return fut.result(timeout=self.timeout)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"MCP call failed: {e}", retryable=True)

    def close(self) -> None:
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)


def call_with_retry(client, name: str, retries: int | None = None, backoff: float | None = None,
                    sleep: Callable[[float], None] = time.sleep, **kwargs) -> dict:
    retries = config.TOOL_RETRIES if retries is None else retries
    backoff = config.TOOL_BACKOFF_BASE if backoff is None else backoff
    last: ToolError | None = None
    for attempt in range(retries):
        try:
            with observe.span("tool", name, attempt=attempt + 1) as step:
                try:
                    return client.call(name, **kwargs)
                except ToolError as e:
                    step.fail("not_possible" if e.not_possible else "error", retryable=e.retryable)
                    step.detail("error", str(e))
                    raise
        except ToolError as e:
            last = e
            if not e.retryable or attempt == retries - 1:
                break
            sleep(backoff * (2 ** attempt))
    raise last  # type: ignore[misc]


def make_client(mode: str | None = None):
    mode = (mode or config.tools_mode()).lower()
    if mode == "mcp":
        return McpClient()
    return InProcessClient()
