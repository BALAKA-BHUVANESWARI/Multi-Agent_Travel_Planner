"""The trip itself: places, what the traveller asked for, suggestions and bookings."""
from typing import NotRequired, TypedDict


class Place(TypedDict):
    slug: str
    name: str
    country: str
    cc: str                       # two-letter country code
    lat: float
    lon: float
    cost_factor: float            # price level compared with India (1.0)
    population: int
    curated: bool
    source: str                   # curated | gazetteer | open-meteo
    admin1: NotRequired[str | None]
    timezone: NotRequired[str | None]


class TripConstraints(TypedDict):
    """What the intake agent understood from the request."""
    origin: str | None
    destination: str | None
    days: int | None
    month: int | None
    start_date: str
    budget: int | None            # in rupees, for the whole group
    travelers: int
    preferences: list[str]
    pace: str                     # normal | relaxed
    today: str
    travel_mode: str | None       # flight | train | bus | car | bike | auto
    origin_geo: NotRequired[Place]
    destination_geo: NotRequired[Place]


class Suggestion(TypedDict):
    """A destination offered when none was named, or as an alternative."""
    slug: str
    name: str
    country: str
    tags: list[str]
    matched: list[str]
    in_season: bool
    fits_budget: bool
    comfortable_fits: bool
    estimate_from: int
    estimate_comfortable: int
    travel_mode: str
    estimated: bool


class Booking(TypedDict):
    """Always a mock: nothing is purchased."""
    booking_id: str
    idempotency_key: str
    status: str
    summary: dict
    cancellation: NotRequired[dict]
