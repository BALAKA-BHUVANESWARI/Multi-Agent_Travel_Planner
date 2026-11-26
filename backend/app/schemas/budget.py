"""What the trip costs."""
from typing import TypedDict


class BudgetLines(TypedDict):
    flight: int                   # travel there and back, whatever the mode
    hotel: int
    activities: int
    food: int


class BudgetReport(TypedDict):
    currency: str
    lines: BudgetLines
    total: int
    budget: int
    over_budget: bool
    remaining: int
    per_person: int
    strategy: str
    estimated: bool
    incomplete: list[str]         # parts that could not be priced
    live: list[str]               # parts priced from a live source
