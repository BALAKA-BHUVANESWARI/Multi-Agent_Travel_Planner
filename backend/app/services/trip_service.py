"""Framework-agnostic request handlers shared by the FastAPI app and the stdlib dev server."""
from __future__ import annotations

from collections import OrderedDict

from app.agents.explore_agent import explore_place
from app.core import config
from app.core import security as guardrails
from app.core.rate_limit import RateLimited, RateLimiter
from app.integrations.openmeteo import ATTRIBUTION as METEO
from app.integrations.openstreetmap import ATTRIBUTION as OSM
from app.integrations.wikipedia import ATTRIBUTION as WIKIPEDIA
from app.integrations.wikivoyage import ATTRIBUTION as WIKI
from app.services.account_service import AccountError, Accounts
from app.services.group_service import clean_group
from app.services.plan_photos import plan_photos
from app.services.trip_toolkit import handlers as toolkit
from app.tools.booking_tools import cancellation_terms
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

ATTRIBUTIONS = [METEO, OSM, WIKI, WIKIPEDIA]
MAX_BODY_CHARS = 20_000
SIGN_IN = "Please sign in first."


class ApiError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


def public_view(state: dict, engine: str = "", metrics: dict | None = None) -> dict:
    """The state minus bulky internals (full ranked candidate list), plus this run's metrics when known."""
    out = dict(state)
    out.pop("memory", None)                                   # saved preferences are only served by /api/me
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


def trip_summary(state: dict) -> dict:
    """The few fields shown in "My trips"."""
    c = state.get("constraints") or {}
    br = state.get("budget_report") or {}
    return {"status": state.get("status"),
            "destination": (c.get("destination_geo") or {}).get("name") or c.get("destination"),
            "origin": (c.get("origin_geo") or {}).get("name") or c.get("origin"),
            "start_date": c.get("start_date"), "days": c.get("days"), "travelers": c.get("travelers"),
            "total_inr": br.get("total"), "booking_id": (state.get("booking") or {}).get("booking_id")}


class PlannerService:
    def __init__(self, planner, limiter: RateLimiter | None = None, require_auth: bool | None = None):
        self.planner = planner
        self.engine = getattr(planner, "engine", "runner")
        self.limiter = limiter                               # None: no limits (tests, scripts)
        self.require_auth = config.auth_required() if require_auth is None else require_auth
        self.accounts = Accounts(planner.deps.store)
        self._metrics: OrderedDict[str, dict] = OrderedDict()      # last run per thread, for GET

    # ------------------------------------------------------------ shared checks
    def _limit(self, bucket: str, user: dict | None, client: str) -> None:
        if self.limiter is None:
            return
        try:
            self.limiter.check(bucket, f"user:{user['id']}" if user else f"ip:{client or 'local'}")
        except RateLimited as e:
            raise ApiError(429, str(e), retry_after=e.retry_after)

    def _user(self, token: str | None, required: bool = False) -> dict | None:
        user = self.accounts.user_for(token)
        if token and user is None:
            raise ApiError(401, "Your session has ended. Please sign in again.")
        if user is None and (required or self.require_auth):
            raise ApiError(401, SIGN_IN)
        return user

    def _may_see(self, thread_id: str, user: dict | None) -> None:
        """A signed-in traveller's trip is only theirs. Others get the same answer as for a missing trip."""
        owner = self.accounts.owner(thread_id)
        if owner and (user is None or user["id"] != owner):
            raise ApiError(404, f"unknown thread '{thread_id}'")

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

    def _with_booking_record(self, state: dict) -> dict:
        """A cancellation happens after the graph has finished, so it is read from the bookings table."""
        key = (state.get("booking") or {}).get("idempotency_key")
        record = self.planner.deps.store.get_booking(key) if key else None
        if not record or not record.get("cancellation"):
            return state
        note = record["cancellation"]
        return {**state, "booking": record, "status": "booking_cancelled",
                "message": f"Booking {record['booking_id']} was cancelled (MOCK).",
                "summary": f"{state.get('summary', '')}\n\n## Cancellation\n{note['cancellation_id']}: "
                           f"{note['status']}"}

    def _view(self, state: dict, user: dict | None, metrics: dict | None = None) -> dict:
        state = self._with_booking_record(state)
        if user and state.get("constraints") and state.get("status") not in ("blocked", "needs_info"):
            self.accounts.record_trip(user["id"], state["thread_id"], trip_summary(state))
        return public_view(state, self.engine, metrics)

    # ---------------------------------------------------------------- planning
    def plan(self, request, group=None, token: str | None = None, client: str = "") -> dict:
        user = self._user(token)
        self._limit("plan", user, client)
        if not isinstance(request, str):
            raise ApiError(422, "'request' must be a string")
        if len(request) > MAX_BODY_CHARS:
            raise ApiError(413, "request body too large")
        try:
            members = clean_group(group)
        except ValueError as e:
            raise ApiError(422, str(e))
        memory = {}
        if user:
            saved = self.accounts.memory(user["id"])
            memory = saved if saved.get("remember", True) else {}
        self._begin_run()
        state, metrics = self._traced("plan", lambda: self.planner.start(
            guardrails.scrub(request), group=members, memory=memory))
        return self._view(state, user, metrics)

    def _begin_run(self) -> None:
        llm = getattr(self.planner.deps, "llm", None)
        if llm:
            llm.begin_run()

    def approve(self, thread_id: str, body: dict, token: str | None = None, client: str = "") -> dict:
        user = self._user(token)
        self._limit("act", user, client)
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        action = body.get("action")
        if action not in ("approve", "revise", "cancel"):
            raise ApiError(422, "'action' must be one of: approve, revise, cancel")
        feedback = body.get("feedback", "")
        if not isinstance(feedback, str) or len(feedback) > config.MAX_REQUEST_CHARS:
            raise ApiError(422, f"'feedback' must be a string under {config.MAX_REQUEST_CHARS} characters")
        self._may_see(thread_id, user)
        self._begin_run()
        try:
            state, metrics = self._traced("approve", lambda: self.planner.resume(
                thread_id, {"action": action, "feedback": guardrails.scrub(feedback)}))
        except KeyError:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        except ValueError as e:
            raise ApiError(409, str(e))
        if user and action == "approve" and state.get("status") == "booked" \
                and self.accounts.owner(thread_id) == user["id"]:
            self.accounts.learn_from_booking(user["id"], state["constraints"])
        return self._view(state, user, metrics)

    def get(self, thread_id: str, token: str | None = None, client: str = "") -> dict:
        user = self._user(token)
        self._limit("read", user, client)
        self._may_see(thread_id, user)
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        return public_view(self._with_booking_record(state), self.engine, self._metrics.get(thread_id))

    # ----------------------------------------------------------------- explore
    def explore(self, body: dict | None, token: str | None = None, client: str = "") -> dict:
        """POST /api/v1/explore {"place": ...}: the place and its top sights, with pictures. Nothing is saved."""
        user = self._user(token)
        self._limit("act", user, client)
        place = body.get("place") if isinstance(body, dict) else None
        if not isinstance(place, str) or not place.strip() or len(place) > 80:
            raise ApiError(422, "Type a city, town or place name (up to 80 characters).")
        verdict = guardrails.check_input(guardrails.scrub(place.strip()), require_topic=False)
        if not verdict["allowed"]:
            raise ApiError(422, verdict["message"])
        try:
            return explore_place(" ".join(place.split()), self.planner.deps)
        except ToolError as e:
            raise ApiError(502 if e.retryable else 422, str(e))

    def photos(self, body: dict | None, token: str | None = None, client: str = "") -> dict:
        """POST /api/v1/photos {"thread_id": ...}: which article shows each sight of a saved plan. Only reads."""
        user = self._user(token)
        self._limit("read", user, client)
        thread_id = body.get("thread_id") if isinstance(body, dict) else None
        if not isinstance(thread_id, str) or not 0 < len(thread_id) <= 64:
            raise ApiError(422, "'thread_id' is required")
        self._may_see(thread_id, user)
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        return plan_photos(state, self.planner.deps)

    # ------------------------------------------------------------ cancellation
    def cancel_booking(self, thread_id: str, body: dict, token: str | None = None, client: str = "") -> dict:
        """Two steps: without ``confirm`` it only shows what cancelling would refund; the traveller must then
        send ``confirm: true``. Cancelling twice returns the same cancellation."""
        user = self._user(token)
        self._limit("act", user, client)
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        self._may_see(thread_id, user)
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        deps = self.planner.deps
        key = (state.get("booking") or {}).get("idempotency_key")
        record = deps.store.get_booking(key) if key else None
        if state.get("status") != "booked" or record is None:
            raise ApiError(409, "There is no booking to cancel for this trip.")
        if record.get("cancellation"):
            return self._view(state, user)
        c = state["constraints"]
        terms_args = {"start_date": c["start_date"], "today": deps.today.isoformat(),
                      "total": state["budget_report"]["total"]}
        if body.get("confirm") is not True:
            return {"thread_id": thread_id, "status": "confirm_cancellation", "booking_id": record["booking_id"],
                    "terms": cancellation_terms(**terms_args)}
        try:
            result = call_with_retry(deps.tools, "cancel_booking", sleep=deps.sleep,
                                     booking_id=record["booking_id"], idempotency_key=key, **terms_args)
        except ToolError as e:
            raise ApiError(502, f"Cancellation failed ({e}). The booking is unchanged; please try again.")
        deps.store.add_cancellation(key, result)
        return self._view(state, user)

    # ------------------------------------------------------------ trip toolkit
    def trip_tool(self, method: str, thread_id: str, tool: str, item_id: str | None = None,
                  body: dict | None = None, token: str | None = None, client: str = "") -> dict:
        """/api/trip/{thread_id}/{tool}[/{item_id}]. The tools read the saved plan and never change it."""
        method, body = method.upper(), body or {}
        user = self._user(token)
        self._limit("read" if method == "GET" else "act", user, client)
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        self._may_see(thread_id, user)
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        if tool not in toolkit.TOOL_NAMES:
            raise ApiError(404, "not found")
        deps = self.planner.deps
        try:
            trip = toolkit.load_trip(thread_id, self._with_booking_record(state))
            if method == "GET" and item_id is None:
                if tool == "companion":
                    return toolkit.companion_view(trip, deps)
                if tool == "emergency":
                    return toolkit.emergency_view(trip)
                if tool == "footprint":
                    return toolkit.footprint_view(trip)
                if tool == "documents":
                    return toolkit.documents_view(trip, deps, signed_in=user is not None)
                return toolkit.expenses_view(trip, deps)
            if tool == "documents":
                if method == "POST" and item_id == "passport-check":
                    return toolkit.passport_check(trip, deps, body)
                if user is None:                              # personal records need an account
                    raise ApiError(401, "Sign in to save documents and tick off the checklist.")
                if method == "POST" and item_id in (None, "tick"):
                    self._claim(thread_id, user, state)
                    (toolkit.tick if item_id else toolkit.save_document)(trip, deps, body)
                    return toolkit.documents_view(trip, deps, signed_in=True)
                if method == "DELETE" and item_id:
                    toolkit.remove(trip, deps, "document", item_id)
                    return toolkit.documents_view(trip, deps, signed_in=True)
            if tool == "expenses":
                if method == "POST" and item_id is None:
                    self._claim(thread_id, user, state)
                    toolkit.add_expense(trip, deps, body)
                    return toolkit.expenses_view(trip, deps)
                if method == "DELETE" and item_id:
                    toolkit.remove(trip, deps, "expense", item_id)
                    return toolkit.expenses_view(trip, deps)
        except toolkit.ToolkitError as e:
            raise ApiError(e.status, e.message)
        except ValueError as e:
            raise ApiError(422, str(e))
        raise ApiError(404, "not found")

    def _claim(self, thread_id: str, user: dict | None, state: dict) -> None:
        """When a signed-in traveller adds records to a trip nobody owns, it becomes theirs, so that only they
        can read what they added."""
        if user and not self.accounts.owner(thread_id):
            self.accounts.record_trip(user["id"], thread_id, trip_summary(state))

    def emergency(self, body: dict | None, token: str | None = None, client: str = "") -> dict:
        """POST /api/emergency: numbers and nearby help for a position, a typed place or a trip's destination.
        Deliberately never needs sign-in, and the numbers are never held back by a rate limit."""
        body = body or {}
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        user = self.accounts.user_for(token)                  # an expired session must not block emergency help
        deps = self.planner.deps
        lat, lon = body.get("lat"), body.get("lon")
        place, thread_id = body.get("place"), body.get("thread_id")
        wants_nearby = body.get("nearby") is True
        if lat is not None or lon is not None:
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)) \
                    or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ApiError(422, "'lat' and 'lon' must be a valid position")
            found = self._nearby(deps, round(lat, 3), round(lon, 3), user, client, remember=False)
            return toolkit.emergency_result({"name": "your position", "source": "device",
                                             "note": toolkit.LOCATION_NOTE}, found.get("country_code", ""),
                                            found, "")
        geo, source = None, "place"
        if isinstance(place, str) and place.strip():
            if len(place) > 80:
                raise ApiError(422, "give a town or city name")
            try:
                geo = call_with_retry(deps.tools, "resolve_place", retries=1, sleep=deps.sleep,
                                      query=place.strip())["geo"]
            except ToolError as e:
                raise ApiError(422, str(e))
        elif isinstance(thread_id, str) and thread_id:
            self._may_see(thread_id, user)
            state = self.planner.get(thread_id)
            geo = ((state or {}).get("constraints") or {}).get("destination_geo")
            source = "trip"
            if not geo:
                raise ApiError(404, f"unknown thread '{thread_id}'")
        else:
            raise ApiError(422, "Share your position, or type the town you are in.")
        found = self._nearby(deps, geo["lat"], geo["lon"], user, client, remember=True) if wants_nearby else None
        where = {"name": geo["name"], "source": source, "country": geo.get("country", ""),
                 "note": f"Distances are measured from the centre of {geo['name']}, not from where you are."}
        return toolkit.emergency_result(where, geo.get("cc", ""), found, geo["name"])

    def _nearby(self, deps, lat: float, lon: float, user: dict | None, client: str, remember: bool) -> dict:
        try:
            self._limit("act", user, client)
        except ApiError as e:
            return {"ok": False, "reason": e.message, "country_code": "", "places": {}, "attribution": []}
        return toolkit.find_nearby(deps, lat, lon, remember)

    # ---------------------------------------------------------------- accounts
    def account(self, method: str, path: str, body: dict | None = None, token: str | None = None,
                client: str = "") -> dict:
        """Every account route, so both web servers stay thin. ``path`` is the part after /api/."""
        body = body or {}
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        route = (method.upper(), path.strip("/"))
        try:
            if route in (("POST", "auth/register"), ("POST", "auth/login")):
                self._limit("auth", None, client)
                action = self.accounts.register if route[1] == "auth/register" else self.accounts.login
                return action(body.get("email"), body.get("password"))
            if route == ("POST", "auth/logout"):
                self.accounts.logout(token)
                return {"ok": True}
            user = self._user(token, required=True)
            self._limit("read", user, client)
            uid = user["id"]
            if route == ("GET", "me"):
                return {"user": user, "memory": self.accounts.memory(uid)}
            if route == ("PUT", "me/memory"):
                return {"memory": self.accounts.save_memory(uid, body)}
            if route == ("DELETE", "me/memory"):
                return {"memory": self.accounts.forget(uid)}
            if route == ("DELETE", "me"):
                if body.get("confirm") is not True:
                    raise ApiError(422, "Send confirm: true to delete the account and its data.")
                self.accounts.delete_user(uid, self.planner.delete)
                self._metrics.clear()
                return {"ok": True}
            if route == ("GET", "trips"):
                return {"trips": self.accounts.trips(uid)}
        except AccountError as e:
            raise ApiError(e.status, e.message)
        raise ApiError(404, "not found")

    def health(self) -> dict:
        llm = getattr(self.planner.deps, "llm", None)
        providers = {r: [p["name"] for p in llm.chain(r)] for r in config.LLM_ROUTING} if llm else {}
        return {"status": "ok", "engine": self.engine, "tools_mode": config.tools_mode(),
                "real_data": config.real_data_enabled(), "llm_providers": providers,
                "llm_stats": llm.summary() if llm else {}, "auth_required": self.require_auth,
                "rate_limited": self.limiter is not None,
                "mode": "llm-assisted" if any(providers.values()) else "rule-based (no API keys set)"}
