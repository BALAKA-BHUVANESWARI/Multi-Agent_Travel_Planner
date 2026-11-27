"""Framework-agnostic request handlers shared by the FastAPI app and the stdlib dev server."""
from __future__ import annotations

import functools
import uuid
from collections import OrderedDict
from contextlib import contextmanager

from app.agents.explore_agent import explore_place
from app.core import config
from app.core import security as guardrails
from app.core.rate_limit import RateLimited, RateLimiter
from app.integrations.openmeteo import ATTRIBUTION as METEO
from app.integrations.openstreetmap import ATTRIBUTION as OSM
from app.integrations.wikipedia import ATTRIBUTION as WIKIPEDIA
from app.integrations.wikivoyage import ATTRIBUTION as WIKI
from app.observability import recorder as observe
from app.observability.privacy import code as short_code
from app.observability.summary import plan_summary, run_status
from app.services import chat_service, speech_service
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
_FROM_ENV = object()


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


def _recorded(kind: str):
    """Keep a record of this request for the dashboard (see app/observability)."""
    def decorate(method):
        @functools.wraps(method)
        def run(self, *args, **kwargs):
            with self._record(kind):
                return method(self, *args, **kwargs)
        return run
    return decorate


def _scrub(text: str) -> str:
    """Withhold a card number, ID number, code or password before anything else sees the text."""
    safe = guardrails.scrub(text)
    if safe != text:
        observe.event("guardrail", "sensitive_data_withheld", "blocked",
                      kind=short_code(guardrails.sensitive_kind(text)))
    return safe


def _check_input(text: str) -> dict:
    verdict = guardrails.check_input(text, require_topic=False)
    observe.event("guardrail", "input_check", "ok" if verdict["allowed"] else "blocked", code=verdict["code"])
    return verdict


class PlannerService:
    def __init__(self, planner, limiter: RateLimiter | None = None, require_auth: bool | None = None,
                 recorder=_FROM_ENV):
        self.recorder = observe.Recorder.from_env() if recorder is _FROM_ENV else recorder      # None: off
        self.planner = planner
        self.engine = getattr(planner, "engine", "runner")
        self.limiter = limiter                               # None: no limits (tests, scripts)
        self.require_auth = config.auth_required() if require_auth is None else require_auth
        self.accounts = Accounts(planner.deps.store)
        self._metrics: OrderedDict[str, dict] = OrderedDict()      # last run per thread, for GET
        self.speech_transport = None                               # None: really call the voice service

    # ------------------------------------------------------------ shared checks
    def _limit(self, bucket: str, user: dict | None, client: str) -> None:
        if self.limiter is None:
            return
        try:
            self.limiter.check(bucket, f"user:{user['id']}" if user else f"ip:{client or 'local'}")
        except RateLimited as e:
            observe.event("guardrail", "rate_limit", "blocked", bucket=bucket)
            raise ApiError(429, str(e), retry_after=e.retry_after)

    def _user(self, token: str | None, required: bool = False) -> dict | None:
        user = self.accounts.user_for(token)
        if user:
            observe.set_run(owner=user["id"])             # so that deleting the account deletes the records too
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

    @contextmanager
    def _record(self, kind: str):
        if self.recorder is None:
            yield
            return
        with self.recorder.run(kind):
            observe.set_run(engine=self.engine)
            yield

    @staticmethod
    def _note_plan(state: dict) -> None:
        """Put the result of a planner call on the request's record."""
        try:
            observe.set_run(status=run_status(state), thread_id=state.get("thread_id"), **plan_summary(state))
        except Exception:                                    # noqa: BLE001 - records must never break a plan
            pass

    def _forget_records(self, **which) -> None:
        recorder = self.recorder or observe.Recorder.existing()
        if recorder is not None:
            recorder.forget(**which)

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
    @_recorded("plan")
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
        safe = _scrub(request)
        observe.hide(*[m["name"] for m in members])
        observe.run_detail("request", safe)
        thread_id = uuid.uuid4().hex[:12]                  # chosen here so a failed run can still be traced to it
        observe.set_run(thread_id=thread_id)
        state, metrics = self._traced("plan", lambda: self.planner.start(
            safe, thread_id=thread_id, group=members, memory=memory))
        self._note_plan(state)
        return self._view(state, user, metrics)

    def _begin_run(self) -> None:
        llm = getattr(self.planner.deps, "llm", None)
        if llm:
            llm.begin_run()

    @_recorded("approve")
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
        observe.set_run(thread_id=thread_id, action=action)
        safe = _scrub(feedback)
        if observe.details_on():
            saved = self.planner.get(thread_id) or {}
            observe.hide(*[m.get("name") for m in saved.get("group") or []])
            observe.run_detail("feedback", safe)
        try:
            state, metrics = self._traced("approve", lambda: self.planner.resume(
                thread_id, {"action": action, "feedback": safe}))
        except KeyError:
            observe.set_run(thread_id=None)                    # no such trip: don't record what was asked for
            raise ApiError(404, f"unknown thread '{thread_id}'")
        except ValueError as e:
            raise ApiError(409, str(e))
        if user and action == "approve" and state.get("status") == "booked" \
                and self.accounts.owner(thread_id) == user["id"]:
            self.accounts.learn_from_booking(user["id"], state["constraints"])
        self._note_plan(state)
        return self._view(state, user, metrics)

    def get(self, thread_id: str, token: str | None = None, client: str = "") -> dict:
        user = self._user(token)
        self._limit("read", user, client)
        self._may_see(thread_id, user)
        state = self.planner.get(thread_id)
        if state is None:
            raise ApiError(404, f"unknown thread '{thread_id}'")
        return public_view(self._with_booking_record(state), self.engine, self._metrics.get(thread_id))

    # ------------------------------------------------------------------- chat
    @_recorded("chat")
    def chat(self, body: dict | None, token: str | None = None, client: str = "") -> dict:
        """POST /api/v1/chat {"message", "thread_id"?, "group"?}. It plans, asks for changes and answers; it has
        no way to approve, book or cancel."""
        user = self._user(token)
        self._limit("act", user, client)
        if not isinstance(body, dict):
            raise ApiError(422, "body must be a JSON object")
        message, thread_id = body.get("message"), body.get("thread_id")
        if not isinstance(message, str) or not message.strip():
            raise ApiError(422, "Type a message first.")
        if len(message) > config.MAX_REQUEST_CHARS:
            raise ApiError(422, f"Keep a message under {config.MAX_REQUEST_CHARS} characters.")
        if thread_id is not None and (not isinstance(thread_id, str) or len(thread_id) > 64):
            raise ApiError(422, "'thread_id' must be a short string")
        clean = _scrub(message.strip())
        observe.run_detail("message", clean)
        verdict = _check_input(clean)
        if not verdict["allowed"]:
            observe.set_run(status="blocked", blocked_code=verdict["code"])
            return chat_service.reply(verdict["message"])
        state = None
        if thread_id:
            try:
                state = self.get(thread_id, token, client)
                observe.set_run(thread_id=thread_id)
                observe.hide(*[m.get("name") for m in state.get("group") or []])
            except ApiError as e:
                if e.status != 404:                           # gone, or not yours: carry on without a plan
                    raise

        def plan(text: str, members: list | None) -> dict:
            return self.plan(text, members or body.get("group"), token, client)

        def revise(feedback: str) -> dict:
            return self.approve(thread_id, {"action": "revise", "feedback": feedback}, token, client)

        def ask_ai(shown: dict, question: str) -> str | None:
            self._begin_run()
            return chat_service.ai_answer(shown, question, getattr(self.planner.deps, "llm", None))

        out = chat_service.respond(clean, state, plan=plan, revise=revise, ask_ai=ask_ai)
        observe.run_detail("reply", out.get("reply"))
        observe.set_run(reply_source=out.get("source"), actions=out.get("actions"))
        made = (out.get("result") or {}).get("thread_id")
        if made:
            observe.set_run(thread_id=made)
        return out

    @_recorded("voice")
    def transcribe(self, audio: bytes, content_type: str, token: str | None = None, client: str = "") -> dict:
        """POST /api/v1/transcribe (the recording as the request body): the words, for the traveller to check."""
        user = self._user(token)
        self._limit("voice", user, client)
        deps = self.planner.deps
        llm = getattr(deps, "llm", None)
        try:
            text = speech_service.transcribe(audio, content_type, env=llm.env if llm else None, store=deps.store,
                                             transport=self.speech_transport)
        except speech_service.SpeechError as e:
            raise ApiError(e.status, e.message)
        safe = guardrails.scrub(text)
        if safe != text:
            observe.event("guardrail", "spoken_sensitive_data", "blocked",
                          kind=short_code(guardrails.sensitive_kind(text)))
            raise ApiError(422, "That sounded like a card number, ID number, code or password, so I've discarded "
                                "the text. Please don't say those here.")
        return {"text": text}

    # ----------------------------------------------------------------- explore
    @_recorded("explore")
    def explore(self, body: dict | None, token: str | None = None, client: str = "") -> dict:
        """POST /api/v1/explore {"place": ...}: the place and its top sights, with pictures. Nothing is saved."""
        user = self._user(token)
        self._limit("act", user, client)
        place = body.get("place") if isinstance(body, dict) else None
        if not isinstance(place, str) or not place.strip() or len(place) > 80:
            raise ApiError(422, "Type a city, town or place name (up to 80 characters).")
        safe = _scrub(place.strip())
        observe.run_detail("place", safe)
        verdict = _check_input(safe)
        if not verdict["allowed"]:
            raise ApiError(422, verdict["message"])
        try:
            return explore_place(" ".join(place.split()), self.planner.deps)
        except ToolError as e:
            raise ApiError(502 if e.retryable else 422, str(e))

    @_recorded("photos")
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
        observe.set_run(thread_id=thread_id)
        return plan_photos(state, self.planner.deps)

    # ------------------------------------------------------------ cancellation
    @_recorded("cancel")
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
        observe.set_run(thread_id=thread_id, confirmed=body.get("confirm") is True)
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
                def delete_trip(thread_id: str) -> None:
                    self.planner.delete(thread_id)
                    self._forget_records(thread_id=thread_id)

                self.accounts.delete_user(uid, delete_trip)
                self._forget_records(owner=uid)
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
        return {"status": "ok", "voice_input": speech_service.available(llm.env if llm else None),
                "engine": self.engine, "tools_mode": config.tools_mode(),
                "real_data": config.real_data_enabled(), "llm_providers": providers,
                "llm_stats": llm.summary() if llm else {}, "auth_required": self.require_auth,
                "recording": "off" if self.recorder is None else
                             "detailed" if self.recorder.details else "basic",
                "rate_limited": self.limiter is not None,
                "mode": "llm-assisted" if any(providers.values()) else "rule-based (no API keys set)"}
