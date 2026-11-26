"""Where the travellers stay."""
from typing import NotRequired, TypedDict


class HotelOption(TypedDict):
    id: str                       # 3star | 2star | budget
    tier: str
    label: str
    price_night_per_room: int
    estimated: bool
    nights: NotRequired[int]       # set on the selected option
    rooms: NotRequired[int]
    total: NotRequired[int]
    live: NotRequired[bool]
    source: NotRequired[str]
    fetched_at: NotRequired[str]


class AccommodationResult(TypedDict):
    """What the accommodation agent writes to the state (key ``hotel``)."""
    selected: HotelOption | None
    estimated: bool
    error: NotRequired[str]
    options: NotRequired[list[HotelOption]]
    live: NotRequired[bool]
    strategy: NotRequired[str]
    source: NotRequired[str | None]
    fetched_at: NotRequired[str | None]
    price_basis: NotRequired[str | None]
    fx_note: NotRequired[str | None]
