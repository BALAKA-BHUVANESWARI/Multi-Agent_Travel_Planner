"""Accounts, saved preferences, trip ownership, booking cancellation and API rate limits."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from app.api.stdlib_server import serve
from app.core.rate_limit import RateLimited, RateLimiter
from app.database.repositories import Store
from app.services.account_service import SESSION_SECONDS, Accounts
from app.services.trip_service import ApiError, PlannerService
from app.tools.booking_tools import cancellation_terms
from app.tools.client import InProcessClient

REQ = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2, love beaches"
PW = "correct-horse-battery"


@pytest.fixture
def service(make, tmp_path):
    return PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False)


def signup(service, email="a@example.com"):
    return service.account("POST", "auth/register", {"email": email, "password": PW})["token"]


def status_of(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value.status


# ------------------------------------------------------------------- accounts
def test_register_login_logout_and_hashed_storage(service):
    token = signup(service)
    assert service.account("GET", "me", token=token)["user"]["email"] == "a@example.com"
    rows = service.accounts._run("SELECT salt, pw FROM users") + service.accounts._run("SELECT token_hash FROM sessions")
    assert PW not in str(rows) and token not in str(rows)
    again = service.account("POST", "auth/login", {"email": "A@Example.com", "password": PW})["token"]
    service.account("POST", "auth/logout", token=token)
    assert status_of(lambda: service.account("GET", "me", token=token)) == 401
    assert service.account("GET", "me", token=again)


@pytest.mark.parametrize("body,code", [({"email": "bad", "password": PW}, 422),
                                       ({"email": "b@example.com", "password": "short"}, 422),
                                       ({"email": "a@example.com", "password": PW}, 409)])
def test_register_rejects(service, body, code):
    signup(service)
    assert status_of(lambda: service.account("POST", "auth/register", body)) == code


def test_wrong_password_and_unknown_email_look_the_same(service):
    signup(service)
    messages = set()
    for email in ("a@example.com", "nobody@example.com"):
        with pytest.raises(ApiError) as e:
            service.account("POST", "auth/login", {"email": email, "password": "wrong-password"})
        messages.add((e.value.status, e.value.message))
    assert len(messages) == 1


def test_sessions_expire():
    now = [1000.0]
    acc = Accounts(Store(), clock=lambda: now[0])
    token = acc.register("a@example.com", PW)["token"]
    assert acc.user_for(token)
    now[0] += SESSION_SECONDS + 1
    assert acc.user_for(token) is None


def test_trips_belong_to_their_owner(service):
    mine, other = signup(service), signup(service, "b@example.com")
    tid = service.plan(REQ, token=mine)["thread_id"]
    assert [t["thread_id"] for t in service.account("GET", "trips", token=mine)["trips"]] == [tid]
    assert service.account("GET", "trips", token=other)["trips"] == []
    for token in (other, None):
        assert status_of(lambda: service.get(tid, token=token)) == 404
        assert status_of(lambda: service.approve(tid, {"action": "approve"}, token=token)) == 404
        assert status_of(lambda: service.cancel_booking(tid, {"confirm": True}, token=token)) == 404
    assert service.get(tid, token=mine)["thread_id"] == tid


def test_guests_work_unless_sign_in_is_required(make, tmp_path):
    guest = PlannerService(make(db=str(tmp_path / "g.db")), require_auth=False)
    assert guest.plan(REQ)["status"] == "awaiting_approval"
    strict = PlannerService(make(db=str(tmp_path / "s.db")), require_auth=True)
    assert status_of(lambda: strict.plan(REQ)) == 401


def test_delete_account_removes_its_data(service):
    token = signup(service)
    tid = service.plan(REQ, token=token)["thread_id"]
    assert status_of(lambda: service.account("DELETE", "me", {}, token=token)) == 422
    service.account("DELETE", "me", {"confirm": True}, token=token)
    assert status_of(lambda: service.account("GET", "me", token=token)) == 401
    assert service.planner.deps.store.load_state(tid) is None
    assert status_of(lambda: service.get(tid)) == 404                  # closed to guests too
    again = signup(service)                                            # the email can be used afresh
    assert service.account("GET", "trips", token=again)["trips"] == []


# --------------------------------------------------------------------- memory
def test_booking_teaches_preferences_and_the_next_plan_uses_them(service):
    token = signup(service)
    first = service.plan(REQ, token=token)
    service.approve(first["thread_id"], {"action": "approve"}, token=token)
    memory = service.account("GET", "me", token=token)["memory"]
    assert memory["home_city"] == "Delhi" and "beach" in memory["preferences"] and "budget" not in memory
    s = service.plan("Plan a 4 day trip to Jaipur in January, budget 2 lakh for 2", token=token)
    assert s["status"] == "awaiting_approval" and s["constraints"]["origin"] == "delhi"
    assert "beach" in s["constraints"]["preferences"]
    assert any("saved profile" in w for w in s["warnings"]) and "memory" not in s


def test_what_the_request_says_beats_memory(service):
    token = signup(service)
    service.account("PUT", "me/memory", {"home_city": "Delhi", "preferences": ["beach"]}, token=token)
    s = service.plan("Plan a 4 day trip to Jaipur from Mumbai in January, budget 2 lakh, love forts", token=token)
    assert s["constraints"]["origin"] == "mumbai" and s["constraints"]["preferences"] == ["history"]


def test_forget_stops_using_and_learning(service):
    token = signup(service)
    service.account("DELETE", "me/memory", token=token)
    first = service.plan(REQ, token=token)
    service.approve(first["thread_id"], {"action": "approve"}, token=token)
    assert service.account("GET", "me", token=token)["memory"] == {"remember": False}
    assert service.plan("4 days in Jaipur in January, budget 2 lakh", token=token)["status"] == "needs_info"


def test_memory_is_validated(service):
    token = signup(service)
    saved = service.account("PUT", "me/memory", {"preferences": ["beach", "hacking"], "travel_mode": "rocket",
                                                 "pace": "x", "extra": 1}, token=token)["memory"]
    assert saved == {"remember": True, "preferences": ["beach"]}
    assert status_of(lambda: service.account("PUT", "me/memory", {"home_city": "<script>"}, token=token)) == 422


# --------------------------------------------------------------- cancellation
def booked(service):
    s = service.plan(REQ)
    return service.approve(s["thread_id"], {"action": "approve"})


def test_cancellation_previews_then_cancels_once(service):
    tools = service.planner.deps.tools
    tid = booked(service)["thread_id"]
    preview = service.cancel_booking(tid, {})
    assert preview["status"] == "confirm_cancellation" and preview["terms"]["refund_pct"] == 100
    assert service.get(tid)["status"] == "booked" and tools.call_count("cancel_booking") == 0
    done = service.cancel_booking(tid, {"confirm": True})
    again = service.cancel_booking(tid, {"confirm": True})
    assert done["status"] == again["status"] == "booking_cancelled"
    assert done["booking"]["cancellation"] == again["booking"]["cancellation"]
    assert tools.call_count("cancel_booking") == 1 and service.get(tid)["status"] == "booking_cancelled"
    assert service.approve(tid, {"action": "approve"})["status"] == "booking_cancelled"


@pytest.mark.parametrize("confirm", ["true", 1, False, None])
def test_only_a_real_true_confirms(service, confirm):
    tid = booked(service)["thread_id"]
    assert service.cancel_booking(tid, {"confirm": confirm})["status"] == "confirm_cancellation"


def test_nothing_to_cancel_and_failed_cancellation(make, tmp_path):
    service = PlannerService(make(tools=InProcessClient(failures={"cancel_booking": -1}),
                                  db=str(tmp_path / "c.db")), require_auth=False)
    waiting = service.plan(REQ)["thread_id"]
    assert status_of(lambda: service.cancel_booking(waiting, {"confirm": True})) == 409
    tid = booked(service)["thread_id"]
    assert status_of(lambda: service.cancel_booking(tid, {"confirm": True})) == 502
    assert service.get(tid)["status"] == "booked"


@pytest.mark.parametrize("today,pct", [("2026-12-01", 100), ("2026-12-03", 100), ("2026-12-04", 50),
                                       ("2026-12-08", 50), ("2026-12-09", 0), ("2026-12-12", 0)])
def test_mock_refund_steps(today, pct):
    assert cancellation_terms("2026-12-10", today, 1000)["refund_pct"] == pct


# ---------------------------------------------------------------- rate limits
def test_sliding_window():
    now = [0.0]
    limiter = RateLimiter({"x": [(2, 60)]}, clock=lambda: now[0])
    limiter.check("x", "a")
    now[0] = 10
    limiter.check("x", "a")
    with pytest.raises(RateLimited) as e:
        limiter.check("x", "a")
    assert e.value.retry_after == 50
    limiter.check("x", "b")                       # another caller is unaffected
    now[0] = 60.5
    limiter.check("x", "a")


def test_service_limits_planning_and_password_guessing(make, tmp_path):
    limiter = RateLimiter({"plan": [(1, 60)], "auth": [(2, 60)]})
    service = PlannerService(make(db=str(tmp_path / "r.db")), limiter=limiter, require_auth=False)
    service.plan(REQ, client="1.1.1.1")
    assert status_of(lambda: service.plan(REQ, client="1.1.1.1")) == 429
    service.plan(REQ, client="2.2.2.2")
    guess = lambda: service.account("POST", "auth/login", {"email": "a@x.com", "password": "nope-nope"}, client="9")
    assert [status_of(guess) for _ in range(3)] == [401, 401, 429]


# ----------------------------------------------------------- over real HTTP
def test_new_routes_over_the_dev_server(make, tmp_path):
    limiter = RateLimiter({"plan": [(1, 60)]})
    service = PlannerService(make(db=str(tmp_path / "h.db")), limiter=limiter, require_auth=False)
    server = serve(service, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1/"

    def call(method, path, body=None, token=None):
        req = urllib.request.Request(base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.load(r), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.load(e), e.headers

    try:
        token = call("POST", "auth/register", {"email": "h@example.com", "password": PW})[1]["token"]
        assert call("GET", "me")[0] == 401
        assert call("PUT", "me/memory", {"pace": "relaxed"}, token)[1]["memory"]["pace"] == "relaxed"
        code, plan, _ = call("POST", "plan", {"request": REQ, "group": [{"name": "A", "likes": ["beaches"]}]}, token)
        assert code == 200 and plan["group_report"][0]["name"] == "A"
        tid = plan["thread_id"]
        assert call("POST", f"approve/{tid}", {"action": "approve"}, token)[1]["status"] == "booked"
        assert call("POST", f"booking/{tid}/cancel", {}, token)[1]["status"] == "confirm_cancellation"
        assert call("POST", f"booking/{tid}/cancel", {"confirm": True}, token)[1]["status"] == "booking_cancelled"
        assert call("GET", "trips", token=token)[1]["trips"][0]["status"] == "booking_cancelled"
        code, _, headers = call("POST", "plan", {"request": REQ}, token)
        assert code == 429 and int(headers["Retry-After"]) > 0
        assert call("DELETE", "me/memory", token=token)[1]["memory"] == {"remember": False}
        assert call("DELETE", "me", {"confirm": True}, token)[0] == 200
    finally:
        server.shutdown()
