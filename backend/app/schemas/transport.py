"""Getting there and back."""
from typing import NotRequired, TypedDict


class TransportOption(TypedDict):
    id: str                       # best | early_late | one_stop
    mode: str                     # flight | train | bus | car | bike | ground
    label: str
    price_pp: int                 # rupees per person, round trip
    duration_h: float             # each way
    stops: int
    depart_out: str
    arrive_out: str
    depart_back: str
    arrive_back: str
    estimated: bool
    total: NotRequired[int]
    note: NotRequired[str]
    leave_days_before: NotRequired[int]
    return_days_after: NotRequired[int]
    live: NotRequired[bool]
    source: NotRequired[str]
    fetched_at: NotRequired[str]


class Journey(TypedDict):
    """When a long overland journey really starts and ends."""
    leave_date: str
    home_date: str
    extra_days: int
    warning: str


class TravelChoice(TypedDict):
    """One card of "how would you like to travel?"."""
    mode: str
    label: str
    available: bool
    estimated: bool
    reason: NotRequired[str]      # why it is not available
    price_pp: NotRequired[int]
    cheapest_pp: NotRequired[int]
    duration_h: NotRequired[float]
    detail: NotRequired[str]
    note: NotRequired[str]
    usual: NotRequired[bool]
    co2_kg_pp: NotRequired[float | None]
    greenest: NotRequired[bool]
    leave_date: NotRequired[str]
    home_date: NotRequired[str]
    extra_days: NotRequired[int]
    warning: NotRequired[str]


class TransportResult(TypedDict):
    """What the transport agent writes to the state (key ``flight``, whatever the mode)."""
    selected: TransportOption | None
    estimated: bool
    error: NotRequired[str]
    options: NotRequired[list[TransportOption]]
    live: NotRequired[bool]
    strategy: NotRequired[str]
    source: NotRequired[str | None]
    fetched_at: NotRequired[str | None]
    price_basis: NotRequired[str | None]
    journey: NotRequired[Journey]
    footprint: NotRequired[dict]
    notices: NotRequired[list[str]]      # warnings this search raised; repeated if a change keeps the result
