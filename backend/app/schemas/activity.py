"""Things to see, do and eat."""
from typing import NotRequired, TypedDict


class Activity(TypedDict):
    id: str
    name: str
    tags: list[str]
    outdoor: bool
    cost: int                     # rupees per person
    hours: float
    slot: str                     # which part of the day suits it
    desc: str
    score: NotRequired[float]
    lat: NotRequired[float]
    lon: NotRequired[float]
    kind: NotRequired[str]
    far: NotRequired[bool]        # a day trip from the centre
    fame: NotRequired[float]


class TopSight(TypedDict):
    rank: int
    id: str
    name: str
    label: str
    best_time: str
    season: str | None
    cost: int
    desc: str


class Eatery(TypedDict):
    name: str
    serves: str                   # veg | nonveg | both | unknown
    cuisine: str
    hours: str
    hours_known: bool
    best_time: str
    desc: str
    source: str                   # wikivoyage | osm
    kind: str


class Dining(TypedDict):
    veg: list[Eatery]
    nonveg: list[Eatery]
    other: list[Eatery]
    data_quality: NotRequired[str]
    attribution: NotRequired[list[str]]
    note: NotRequired[str]


class ActivityResult(TypedDict):
    """What the activity agent writes to the state (key ``activities``)."""
    candidates: list[Activity]
    estimated: bool
    error: NotRequired[str]
    tips: NotRequired[list[dict]]
    nearby: NotRequired[list[dict]]
    attribution: NotRequired[list[str]]
    llm_reranked: NotRequired[bool]
    data_quality: NotRequired[str]
    top_sights: NotRequired[list[TopSight]]
    top_sights_note: NotRequired[str]
    dining: NotRequired[Dining]
    notices: NotRequired[list[str]]      # warnings this search raised; repeated if a change keeps the result
