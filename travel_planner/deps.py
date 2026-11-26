"""Dependency container shared by all nodes (tools, LLM, store, clock, sleep)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from . import config
from .llm.router import LLMRouter
from .store import Store
from .tools.client import make_client
from .trace import Tracer


@dataclass
class Deps:
    tools: object
    store: Store
    llm: LLMRouter
    today: date = field(default_factory=date.today)
    sleep: Callable[[float], None] = time.sleep
    tracer: Tracer = field(default_factory=Tracer)
    ask_travel_mode: bool = False       # ask how to travel when the request does not say (the API turns this on)

    @classmethod
    def default(cls, db: str | None = None, tools_mode: str | None = None, today: date | None = None,
                ask_travel_mode: bool | None = None) -> "Deps":
        store = Store(db or config.db_path())
        ask = config.ask_travel_mode() if ask_travel_mode is None else ask_travel_mode
        return cls(tools=make_client(tools_mode), store=store, llm=LLMRouter(store=store),
                   today=today or date.today(), ask_travel_mode=ask)
