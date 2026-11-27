"""Who may see the dashboard, and what its web addresses give back."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from app.api import stdlib_server
from app.observability import recorder as observe
from app.services.dashboard_service import SESSION_SECONDS, DashboardService
from app.services.trip_service import ApiError, PlannerService

GOA = "Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2 by flight"
PASSWORD = "a-long-test-password"
VIEWS = ("options", "overview", "agents", "ai", "runs", "retrieval", "logs")


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("DASHBOARD", "1")
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)


@pytest.fixture
def board(make, tmp_path):
    return DashboardService(PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False), clock=Clock())


def token_of(board):
    return board.login({"password": PASSWORD}, "me")["token"]


def status_of(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value.status


@pytest.fixture(autouse=True)
def _off_unless_asked(monkeypatch):
    for name in ("DASHBOARD", "DASHBOARD_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("env,reason", [
    ({}, "off"), ({"DASHBOARD_PASSWORD": PASSWORD}, "off"), ({"DASHBOARD": "1"}, "no_password"),
    ({"DASHBOARD": "1", "DASHBOARD_PASSWORD": "short"}, "password_too_short"),
    ({"DASHBOARD": "0", "DASHBOARD_PASSWORD": PASSWORD}, "off")])
def test_the_dashboard_is_off_unless_switched_on_with_a_password(board, monkeypatch, env, reason):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert board.status() == {"enabled": False, "reason": reason, "min_password": 8}
    for call in (lambda: board.login({"password": env.get("DASHBOARD_PASSWORD", "x")}),
                 lambda: board.get("overview", {}, "token"), lambda: board.export({"what": "requests"}, "token")):
        assert status_of(call) == 404


def test_nothing_is_shown_without_signing_in(on, board):
    for view in VIEWS + ("runs/" + "0" * 32,):
        assert status_of(lambda: board.get(view, {}, None)) == 401
        assert status_of(lambda: board.get(view, {}, "made-up-token")) == 401
    assert status_of(lambda: board.export({"what": "logs"}, None)) == 401
    assert status_of(lambda: board.login({"password": "wrong password"}, "me")) == 401
    assert status_of(lambda: board.login({}, "me")) == 422
    assert status_of(lambda: board.login(None, "me")) == 422


def test_a_planner_sign_in_does_not_open_the_dashboard(on, board):
    account = board.service.account("POST", "auth/register", {"email": "a@example.com", "password": PASSWORD})
    assert status_of(lambda: board.get("overview", {}, account["token"])) == 401


def test_password_guessing_is_slowed_even_with_rate_limits_off(on, board):
    for _ in range(5):
        assert status_of(lambda: board.login({"password": "guess-guess"}, "me")) == 401
    assert status_of(lambda: board.login({"password": PASSWORD}, "me")) == 429
    board.clock.now += 61
    assert token_of(board)


def test_sign_ins_end_by_time_sign_out_or_a_new_password(on, board, monkeypatch):
    first = token_of(board)
    assert board.get("overview", {}, first)
    board.logout(first)
    assert status_of(lambda: board.get("overview", {}, first)) == 401
    second = token_of(board)
    board.clock.now += SESSION_SECONDS + 1
    assert status_of(lambda: board.get("overview", {}, second)) == 401
    board.clock.now += 3600
    third = token_of(board)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "another-long-password")
    assert status_of(lambda: board.get("overview", {}, third)) == 401


def test_every_tab_shows_real_records_and_looking_adds_none(on, board):
    state = board.service.plan(GOA)
    board.service.approve(state["thread_id"], {"action": "approve"})
    token = token_of(board)
    store = board.service.recorder.store
    before = len(store.runs()), len(store.spans())
    options, overview, agents, ai, runs, retrieval, logs = (board.get(view, {}, token) for view in VIEWS)
    assert options["recorded"] == 2 and "flight" in options["agents"] and options["recording"]["mode"] == "basic"
    assert overview["requests"] == 2 and overview["bookings"] == 1 and overview["plans"]["full"]["count"] == 1
    assert overview["evals"]["rows"] and overview["limits"] == []                 # no keys: nothing to count
    assert {a["agent"] for a in agents["agents"]} >= {"flight", "hotel", "weather", "activities", "writer"}
    assert ai["total_calls"] == 0 and ai["models"] == []                    # no keys: no model is ever asked
    assert runs["total"] == 2
    trace = board.get("runs/" + runs["runs"][-1]["id"], {}, token)
    assert trace["steps"] and trace["linked"][0]["kind"] == "approve" and not trace["has_texts"]
    assert retrieval["in_plans"]["plans"] == 1 and logs["total"] > 20
    for what in ("requests", "agents", "ai_calls", "lookups", "logs"):
        body, kind, name = board.export({"what": what, "format": "json"}, token)
        assert kind == "application/json" and name.startswith(f"metrics-{what}-")
        assert bool(json.loads(body)) == (what != "ai_calls")                  # with no keys no model was asked
        assert board.export({"what": what}, token)[1] == "text/csv"
    assert (len(store.runs()), len(store.spans())) == before
    assert status_of(lambda: board.get("secrets", {}, token)) == 404
    assert status_of(lambda: board.get("runs/" + "f" * 32, {}, token)) == 404
    assert status_of(lambda: board.get("logs", {"level": "loud"}, token)) == 422
    assert status_of(lambda: board.get("overview", {"period": "never"}, token)) == 422
    assert status_of(lambda: board.export({"what": "passwords"}, token)) == 422


def test_reading_uses_its_own_connection(on, make, tmp_path):
    board = DashboardService(PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False))
    board.service.plan(GOA)
    assert board._store() is not board.service.recorder.store
    assert board.get("overview", {}, token_of(board))["requests"] == 1


def test_plans_keep_recording_while_the_dashboard_is_being_read(on, make, tmp_path):
    board = DashboardService(PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False))
    token, problems, stop = token_of(board), [], threading.Event()

    def look():
        while not stop.is_set():
            try:
                for view in VIEWS:
                    board.get(view, {}, token)
            except Exception as e:                                          # noqa: BLE001
                problems.append(repr(e))
                return

    watcher = threading.Thread(target=look)
    watcher.start()
    try:
        for _ in range(5):
            assert board.service.plan(GOA)["status"] == "awaiting_approval"
    finally:
        stop.set()
        watcher.join(timeout=30)
    assert not problems and board.service.recorder.errors == 0
    assert board.get("overview", {}, token)["requests"] == 5


def test_earlier_records_can_be_viewed_with_recording_off(on, make, tmp_path, monkeypatch):
    PlannerService(make(db=str(tmp_path / "a.db"))).plan(GOA)
    monkeypatch.setenv("OBSERVABILITY", "0")
    board = DashboardService(PlannerService(make(db=str(tmp_path / "b.db")), require_auth=False))
    out = board.get("overview", {}, token_of(board))
    assert out["requests"] == 1 and out["recording"]["mode"] == "off"


def test_recording_off_and_nothing_recorded(on, make, monkeypatch):
    monkeypatch.setenv("OBSERVABILITY", "0")
    board = DashboardService(PlannerService(make(), require_auth=False))
    assert board.get("overview", {}, token_of(board))["requests"] == 0


# ------------------------------------------------------------------ over HTTP
def call(base, path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check_over_http(base):
    status, headers, body = call(base, "/api/v1/dashboard/status")
    assert status == 200 and json.loads(body)["enabled"] and headers.get("Cache-Control",
                                                                       headers.get("cache-control")) == "no-store"
    assert call(base, "/api/v1/dashboard/overview")[0] == 401
    assert call(base, "/api/v1/dashboard/login", "POST", {"password": "nope-nope"})[0] == 401
    token = json.loads(call(base, "/api/v1/dashboard/login", "POST", {"password": PASSWORD})[2])["token"]
    status, _, body = call(base, "/api/v1/dashboard/overview?period=today", token=token)
    assert status == 200 and json.loads(body)["requests"] == 1
    runs = json.loads(call(base, "/api/v1/dashboard/runs?kind=plan", token=token)[2])["runs"]
    assert call(base, f"/api/v1/dashboard/runs/{runs[0]['id']}", token=token)[0] == 200
    status, headers, body = call(base, "/api/v1/dashboard/export?what=requests&format=csv", token=token)
    lowered = {k.lower(): v for k, v in headers.items()}
    assert status == 200 and lowered["content-disposition"].startswith('attachment; filename="metrics-requests-')
    assert body.startswith("﻿".encode()) and lowered["content-type"].startswith("text/csv")
    assert call(base, "/api/v1/dashboard/logout", "POST", {}, token)[0] == 200
    assert call(base, "/api/v1/dashboard/overview", token=token)[0] == 401
    for page in ("/dashboard", "/dashboard/"):
        status, headers, body = call(base, page)
        assert status == 200 and b"<title>" in body


def test_over_the_dev_server(on, make, tmp_path):
    service = PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False)
    service.plan(GOA)
    server = stdlib_server.serve(service, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        check_over_http(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()


def test_over_fastapi(on, make, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import create_app
    service = PlannerService(make(db=str(tmp_path / "t.db")), require_auth=False)
    service.plan(GOA)
    client = TestClient(create_app(service))
    assert client.get("/api/v1/dashboard/overview").status_code == 401
    token = client.post("/api/v1/dashboard/login", json={"password": PASSWORD}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/dashboard/status").json()["enabled"]
    assert client.get("/api/v1/dashboard/overview?period=today", headers=auth).json()["requests"] == 1
    run = client.get("/api/v1/dashboard/runs?kind=plan", headers=auth).json()["runs"][0]
    assert client.get(f"/api/v1/dashboard/runs/{run['id']}", headers=auth).status_code == 200
    export = client.get("/api/v1/dashboard/export?what=requests", headers=auth)
    assert export.headers["content-disposition"].startswith('attachment; filename="metrics-requests-')
    assert client.get("/dashboard").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
