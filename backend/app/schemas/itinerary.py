"""The day-by-day plan."""
from typing import NotRequired, TypedDict


class ItineraryItem(TypedDict):
    type: str                     # transport | hotel | activity
    name: str
    start: str                    # HH:MM
    end: str
    start_min: int                # minutes after midnight
    end_min: int
    leg: NotRequired[str]         # arrival | departure
    id: NotRequired[str]
    desc: NotRequired[str]
    slot: NotRequired[str]
    tags: NotRequired[list[str]]
    outdoor: NotRequired[bool]
    cost_pp: NotRequired[int]
    cost_total: NotRequired[int]
    note: NotRequired[str | None]
    lat: NotRequired[float]
    lon: NotRequired[float]
    far: NotRequired[bool]


class DayPlan(TypedDict):
    day: int
    date: str
    kind: str                     # arrival | full | departure
    weather: dict | None
    rainy: bool
    items: list[ItineraryItem]
    notes: list[str]


class Itinerary(TypedDict):
    start_date: str
    end_date: str
    nights: int
    destination: str
    days: list[DayPlan]
    swaps: list
