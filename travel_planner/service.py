"""Framework-agnostic request handlers shared by the FastAPI app and the stdlib dev server."""
from __future__ import annotations

from collections import OrderedDict

from . import config, guardrails
from .rag.wikivoyage import ATTRIBUTION as WIKI
from .tools.openmeteo import ATTRIBUTION as METEO
from .tools.osm import ATTRIBUTION as OSM
from .tools.wikipedia import ATTRIBUTION as WIKIPEDIA

ATTRIBUTIONS = [METEO, OSM, WIKI, WIKIPEDIA]
MAX_BODY_CHARS = 20_000


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def public_view(state: dict, engine: str = "", metrics: dict | None = None) -> dict:
    """The state minus bulky internals (full ranked candidate list), plus this run's metrics when known."""
    out = dict(state)
    if metrics:
        out["metrics"] = metrics
    acts = out.get("activities")
    if isinstance(acts, dict):
        acts = dict(acts)
        acts["candidates"] = [{"id": c["id"], "name": c["name"], "cost": c["cost"]}
                              for c in acts.get("candidates", [])][:30]
        out["activities"] = acts
    out["engine"] = engine
    out["attributions"] = ATTRIBUTIONS
    return out


class PlannerService:
    def __init__(self, planner):
        self.planner = planner
        self.engine = getattr(planner, "engine", "runner")
        self._metrics: OrderedDict[str, dict] = OrderedDict()      # last run per thread, for GET

    def _traced(self, kind: str, run):
        """Run `run()` (a planner call) and attach timing/cost metrics to its result."""
        deps = self.planner.deps
        tracer = getattr(deps, "tracer", None)
        if tracer is None:
            return run(), None
        base = tracer.start(deps)
        state = run()
        metrics = tracer.finish(base, deps, state, kind, self.engine)
        tracer.write(metrics)
        if metrics.get("thread_id"):
            self._metrics[metrics["thread_id"]] = metrics
            while len(self._metrics) > 200:
                self._metrics.popitem(last=False)
        return state, metrics

    def plan(self, request) -> dict:
        if not isinstance(request, str):
            raise ApiError(422, "'request' must be a string")
        if len(request) > MAX_BODY_CHARS:
            raise ApiError(413, "request body too large")
        self._begin_run()
        state, metrics = self._traced("plan", lambda: self.planner.start(guardrails.scrub(request)))
        return public_view(state, self.engine, metrics)

    def _begin_run(self) -> None:
        llm = getattr(self.planner.deps, "llm", None)
        if llm:
            llm.begin_run()

    def approve(self, thread_id: str, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        action = body.get("action")
        if action not in ("approve", "revise", "cancel"):
            raise ApiError(422, "'action' must be one of: approve, revise, cancel")
        feedback = body.get("feedback", "")
        if not isinstance(feedback, str) or len(feedback) > config.MAX_REQUEST_CHARS:
            raise ApiError(422, f"'feedback' must be a string under {config.MAX_REQUEST_CHARS} characters")
        self._begin_run()
        try:
            state, metrics = self._traced("approve", lambda: self.planner.resume(
                thread_id, {"action": action, "feedback": guardrails.scrub(feedback)}))
        except KeyError:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        except ValueError as e:
            raise ApiError(409, str(e))
        return public_view(state, self.engine, metrics)

    def get(self, thread_id: str) -> dict:
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        return public_view(state, self.engine, self._metrics.get(thread_id))

    def health(self) -> dict:
        llm = getattr(self.planner.deps, "llm", None)
        providers = {r: [p["name"] for p in llm.chain(r)] for r in config.LLM_ROUTING} if llm else {}
        return {"status": "ok", "engine": self.engine, "tools_mode": config.tools_mode(),
                "real_data": config.real_data_enabled(), "llm_providers": providers,
                "llm_stats": llm.summary() if llm else {},
                "mode": "llm-assisted" if any(providers.values()) else "rule-based (no API keys set)"}
