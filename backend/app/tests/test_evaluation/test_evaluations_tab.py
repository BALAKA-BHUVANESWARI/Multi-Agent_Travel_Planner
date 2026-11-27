"""The dashboard's Evaluations tab: sign-in, what it shows, hand checks and downloads."""
import csv
import io
import json

import pytest

from app.evaluation import results
from app.services.dashboard_service import DashboardService
from app.services.trip_service import ApiError, PlannerService

PASSWORD = "dashboard-password"


@pytest.fixture
def board(make, monkeypatch):
    monkeypatch.setenv("DASHBOARD", "1")
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    found = DashboardService(PlannerService(make(), require_auth=False))
    return found, found.login({"password": PASSWORD})["token"]


def saved():
    results.save("offline", {"id": "20260101-100000-aaaa", "metrics": {"planner": {"outcome": {"share": 1.0}}},
                             "groups": {}, "cases": [{"group": "chat", "id": "c", "text": "=1+1", "passed": True,
                                                      "failed": [], "known_gap": ""}]})
    old = results.save("live", {"id": "20260101-100000-bbbb", "items": [
        {"id": "groq.a", "provider": "groq", "group": "chat", "case": "a", "status": "pass", "answer": "old"}]})
    new = results.save("live", {"id": "20260102-100000-cccc", "items": [
        {"id": "groq.a", "provider": "groq", "group": "chat", "case": "a", "status": "pass", "answer": "new"},
        {"id": "groq.b", "provider": "groq", "group": "chat", "case": "b", "status": "not_run"}]})
    return old, new


def test_it_needs_the_dashboard_sign_in(board):
    dashboard, _ = board
    for call in (lambda: dashboard.get("evals", {}), lambda: dashboard.export({"what": "eval_results"}),
                 lambda: dashboard.mark({"eval_run": "x", "item": "y", "verdict": "good"})):
        with pytest.raises(ApiError) as e:
            call()
        assert e.value.status == 401


def test_with_nothing_saved_it_says_so(board):
    dashboard, token = board
    found = dashboard.get("evals", {}, token)
    assert found["offline"]["latest"] is None and found["live"]["chosen"] is None and found["voice"]["latest"] is None


def test_the_newest_run_is_shown_unless_another_is_chosen(board):
    dashboard, token = board
    old, new = saved()
    assert dashboard.get("evals", {}, token)["live"]["chosen"]["id"] == new
    assert dashboard.get("evals", {"live": old}, token)["live"]["chosen"]["id"] == old
    assert dashboard.get("evals", {"live": "nonsense"}, token)["live"]["chosen"]["id"] == new


def test_hand_checks(board):
    dashboard, token = board
    _, new = saved()
    dashboard.mark({"eval_run": new, "item": "groq.a", "verdict": "wrong"}, token)
    chosen = dashboard.get("evals", {}, token)["live"]["chosen"]
    assert [i["mark"] for i in chosen["items"]] == ["wrong", ""]
    assert chosen["hand"]["groq"] == {"good": 0, "wrong": 1, "answers": 1}
    dashboard.mark({"eval_run": new, "item": "groq.a", "verdict": ""}, token)
    assert results.marks() == {}
    for body, status in (({"eval_run": new, "item": "groq.a", "verdict": "perfect"}, 422),
                         ({"eval_run": new, "item": 5, "verdict": "good"}, 422),
                         ({"eval_run": "../../x", "item": "groq.a", "verdict": "good"}, 404),
                         ({"eval_run": new, "item": "groq.zzz", "verdict": "good"}, 404)):
        with pytest.raises(ApiError) as e:
            dashboard.mark(body, token)
        assert e.value.status == status


def test_download_has_a_row_for_every_saved_case(board):
    dashboard, token = board
    saved()
    body, kind, name = dashboard.export({"what": "eval_results", "format": "csv"}, token)
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    assert kind == "text/csv" and name.startswith("metrics-eval_results-") and len(rows) == 4
    assert next(r for r in rows if r["test"] == "offline")["text"] != "=1+1"        # not run as a formula
    body, kind, _ = dashboard.export({"what": "eval_results", "format": "json"}, token)
    assert kind == "application/json" and "groq" in body.decode()
