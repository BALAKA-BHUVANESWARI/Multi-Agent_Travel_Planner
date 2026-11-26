"""Request handling for the trip toolkit. ``PlannerService`` has already checked who is asking and that they may
see the trip; these functions only read the saved plan and the trip's own records (they never change the plan)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.data.curated_destinations import place_name
from app.services import export_service
from app.services.trip_toolkit import (
    companion,
    documents,
    emergency,
    expenses,
    footprint,
)
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

TOOL_NAMES = ("companion", "emergency", "documents", "footprint", "expenses")
LOCATION_NOTE = ("Your position was sent to this app's server and to OpenStreetMap's map service to find places "
                 "nearby. The app does not save it.")
NO_COUNTRY = ("I could not tell which country this is, so I have no checked numbers to show. Type the name of "
              "the town you are in to get them.")


class ToolkitError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class Trip:
    thread_id: str
    state: dict
    constraints: dict
    selected: dict | None
    destination: str
    origin_cc: str
    dest_cc: str
    start: date
    end: date
    leave: date
    home: date

    @property
    def international(self) -> bool:
        return bool(self.origin_cc and self.dest_cc and self.origin_cc != self.dest_cc)


def load_trip(thread_id: str, state: dict) -> Trip:
    c = state.get("constraints") or {}
    if not state.get("budget_report") or not state.get("itinerary") or not c.get("start_date"):
        raise ToolkitError(409, "Make a plan first: the trip tools work from a finished plan.")
    flight = state.get("flight") or {}
    start = date.fromisoformat(c["start_date"])
    end = start + timedelta(days=int(c["days"]) - 1)
    journey = flight.get("journey") or {}
    return Trip(thread_id=thread_id, state=state, constraints=c, selected=flight.get("selected"),
                destination=place_name(c, "destination"),
                origin_cc=(c.get("origin_geo") or {}).get("cc") or "",
                dest_cc=(c.get("destination_geo") or {}).get("cc") or "", start=start, end=end,
                leave=date.fromisoformat(journey["leave_date"]) if journey.get("leave_date") else start,
                home=date.fromisoformat(journey["home_date"]) if journey.get("home_date") else end)


# ---------------------------------------------------------------- read views
def companion_view(trip: Trip, deps) -> dict:
    out = companion.guide(trip.constraints, trip.state.get("weather"), trip.state.get("itinerary"), trip.selected,
                          trip.origin_cc, trip.dest_cc)
    try:
        local = call_with_retry(deps.tools, "local_tips", retries=1, sleep=deps.sleep,
                                destination=trip.constraints["destination"],
                                destination_geo=trip.constraints.get("destination_geo"))
    except (ToolError, KeyError, ValueError):
        local = {"sections": [], "attribution": []}
    return {**out, "destination": trip.destination, "local": local}


def footprint_view(trip: Trip) -> dict:
    return footprint.compare(trip.constraints, (trip.selected or {}).get("mode"))


def emergency_view(trip: Trip) -> dict:
    return {"where": {"name": trip.destination, "source": "trip"},
            "numbers": emergency.numbers_for(trip.dest_cc), "call_first": emergency.CALL_FIRST,
            "links": emergency.search_links(trip.destination), "nearby": None}


def documents_view(trip: Trip, deps, signed_in: bool) -> dict:
    entries = deps.store.list_items(trip.thread_id, "document") if signed_in else []
    ticks = {t["check_id"] for t in deps.store.list_items(trip.thread_id, "tick")} if signed_in else set()
    items = documents.checklist(trip.constraints, trip.selected, trip.origin_cc, trip.dest_cc)
    for item in items:
        item["done"] = item["id"] in ticks
    todo = documents.reminders(trip.constraints, trip.selected, entries, deps.today, trip.home, trip.leave,
                               trip.international)
    return {"destination": trip.destination, "international": trip.international,
            "schengen": trip.international and trip.dest_cc in documents.SCHENGEN,
            "trip_dates": {"start": trip.start.isoformat(), "end": trip.end.isoformat()},
            "checklist": items, "entries": entries, "kinds": list(documents.KINDS), "reminders": todo,
            "calendar": export_service.ics(trip.thread_id, trip.destination, todo) if todo else "",
            "can_save": signed_in, "disclaimer": documents.DISCLAIMER, "number_warning": documents.NO_NUMBERS}


def expenses_view(trip: Trip, deps) -> dict:
    entries = deps.store.list_items(trip.thread_id, "expense")
    entries.sort(key=lambda e: e["date"])
    status = trip.state.get("status")
    return {"destination": trip.destination, "entries": entries, "categories": list(expenses.CATEGORIES),
            "labels": expenses.LABELS, "today": deps.today.isoformat(), "csv": export_service.to_csv(entries),
            "summary": expenses.summary(trip.state["budget_report"], trip.constraints, entries, deps.today,
                                        trip.home, cancelled=status in ("cancelled", "booking_cancelled"))}


# ---------------------------------------------------------------- changes
def passport_check(trip: Trip, deps, body: dict) -> dict:
    """Nothing is stored: the dates are compared with the trip and forgotten."""
    expiry = documents.parse_date(body.get("expiry"), "the expiry date")
    if expiry is None:
        raise ValueError("enter the passport's expiry date")
    return documents.passport_check(expiry, trip.start, trip.end, deps.today, trip.origin_cc, trip.dest_cc,
                                    issued=documents.parse_date(body.get("issued"), "the issue date"))


def save_document(trip: Trip, deps, body: dict) -> None:
    entry = documents.clean_entry(body)
    item_id = body.get("id")
    if item_id:
        if not isinstance(item_id, str) or not deps.store.update_item(trip.thread_id, "document", item_id, entry):
            raise ToolkitError(404, "That document entry no longer exists.")
    else:
        deps.store.add_item(trip.thread_id, "document", entry, documents.MAX_ENTRIES)


def tick(trip: Trip, deps, body: dict) -> None:
    check_id = body.get("check_id")
    known = {i["id"] for i in documents.checklist(trip.constraints, trip.selected, trip.origin_cc, trip.dest_cc)}
    if check_id not in known:
        raise ToolkitError(422, "unknown checklist item")
    existing = [t for t in deps.store.list_items(trip.thread_id, "tick") if t["check_id"] == check_id]
    if body.get("done") is True and not existing:
        deps.store.add_item(trip.thread_id, "tick", {"check_id": check_id}, limit=100)
    elif body.get("done") is not True:
        for t in existing:
            deps.store.delete_item(trip.thread_id, "tick", t["id"])


def add_expense(trip: Trip, deps, body: dict) -> None:
    deps.store.add_item(trip.thread_id, "expense", expenses.clean_entry(body, deps.today), expenses.MAX_ENTRIES)


def remove(trip: Trip, deps, kind: str, item_id: str) -> None:
    if not deps.store.delete_item(trip.thread_id, kind, item_id):
        raise ToolkitError(404, "That entry no longer exists.")


# ---------------------------------------------------------------- emergency, with or without a trip
def find_nearby(deps, lat: float, lon: float, remember: bool) -> dict:
    try:
        return call_with_retry(deps.tools, "find_help_nearby", retries=1, sleep=deps.sleep, lat=lat, lon=lon,
                               remember=remember)
    except (ToolError, KeyError, ValueError) as e:
        return {"ok": False, "reason": f"The nearby search failed ({e}).", "country_code": "",
                "places": emergency.build_places([], 0, 0), "attribution": []}


def emergency_result(where: dict, cc: str, nearby: dict | None, link_name: str) -> dict:
    numbers = emergency.numbers_for(cc) if cc else {"verified": False, "cc": "", "calls": [], "message": NO_COUNTRY}
    return {"where": where, "numbers": numbers, "nearby": nearby, "call_first": emergency.CALL_FIRST,
            "map_note": emergency.MAP_NOTE, "links": emergency.search_links(link_name)}
