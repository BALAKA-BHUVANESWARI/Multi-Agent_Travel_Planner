"""LangGraph wiring: the SAME node functions and routers as the dependency-free runner.

    START -> guardrail -(blocked)-> END
          -> intake -(missing info)-> END
          -> supervisor -> [flight | hotel | weather | activities] (parallel) -> merge
          -> budget -(over, retries<2)-> supervisor
          -> critic -(blocking, retries<2)-> supervisor
          -> present -> approval (interrupt) -(changes, revisions<2)-> supervisor
                                              -(approved)-> book -> writer -> END

Requires: langgraph (and langgraph-checkpoint-sqlite for a durable checkpointer).
"""
from __future__ import annotations

import sqlite3
import uuid

from app.core.tracing import wrap
from app.graph import edges as routing
from app.graph.deps import Deps
from app.graph.nodes import NODES, WORKERS, approval_node
from app.graph.state import TripState, initial_state
from app.observability import recorder as observe


def build_graph(deps: Deps, checkpointer=None):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    def bind(fn):
        return lambda state: fn(state, deps)

    g = StateGraph(TripState)
    for name, fn in NODES.items():
        g.add_node(name, bind(wrap(name, fn)))

    def approval(state: TripState):
        # Pauses the graph; the checkpointer persists state until Command(resume=decision) arrives.
        decision = interrupt({"kind": "approval", "message": state.get("message"),
                              "pending": state.get("pending_approval")})
        with observe.adopt(state.get("thread_id")):             # so its safety decisions are recorded
            return approval_node(state, decision, deps)

    g.add_node("approval", approval)

    g.add_edge(START, "guardrail")
    g.add_conditional_edges("guardrail", routing.after_guardrail, {"intake": "intake", "end": END})
    g.add_conditional_edges("intake", routing.after_intake, {"supervisor": "supervisor", "end": END})
    for w in WORKERS:                              # parallel fan-out
        g.add_edge("supervisor", w)
    g.add_edge(list(WORKERS), "merge")             # join: waits for all four
    g.add_edge("merge", "budget")
    g.add_conditional_edges("budget", routing.after_budget, {"supervisor": "supervisor", "critic": "critic"})
    g.add_conditional_edges("critic", routing.after_critic, {"supervisor": "supervisor", "present": "present"})
    g.add_edge("present", "approval")
    g.add_conditional_edges("approval", routing.after_approval,
                            {"book": "book", "supervisor": "supervisor", "present": "present", "end": END})
    g.add_conditional_edges("book", routing.after_book, {"writer": "writer", "present": "present"})
    g.add_edge("writer", END)
    return g.compile(checkpointer=checkpointer)


def make_checkpointer(path: str):
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


class GraphPlanner:
    """Same public interface as runner.Planner: start / resume / get."""

    engine = "langgraph"

    def __init__(self, deps: Deps | None = None, checkpoint_path: str | None = None):
        self.deps = deps or Deps.default()
        path = checkpoint_path or (self.deps.store.path + ".graph" if self.deps.store.path != ":memory:"
                                   else ":memory:")
        self.graph = build_graph(self.deps, make_checkpointer(path))

    def _cfg(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}

    def start(self, request: str, thread_id: str | None = None, group: list | None = None,
              memory: dict | None = None) -> dict:
        tid = thread_id or uuid.uuid4().hex[:12]
        self.graph.invoke(initial_state(request, tid, group, memory), self._cfg(tid))
        state = self.get(tid)
        self.deps.store.save_state(tid, state)
        return state

    def resume(self, thread_id: str, decision: dict) -> dict:
        from langgraph.types import Command
        state = self.get(thread_id)
        if state is None:
            raise KeyError(f"unknown thread '{thread_id}'")
        if state.get("status") in ("booked", "cancelled"):
            return state
        if state.get("status") != "awaiting_approval":
            raise ValueError(f"thread is '{state.get('status')}', not awaiting approval")
        self.graph.invoke(Command(resume=decision), self._cfg(thread_id))
        state = self.get(thread_id)
        self.deps.store.save_state(thread_id, state)
        return state

    def delete(self, thread_id: str) -> None:
        self.deps.store.delete_trip(thread_id)
        try:                                      # older checkpointer versions cannot delete a thread
            self.graph.checkpointer.delete_thread(thread_id)
        except (AttributeError, NotImplementedError):
            pass

    def get(self, thread_id: str) -> dict | None:
        snap = self.graph.get_state(self._cfg(thread_id))
        return dict(snap.values) if snap and snap.values else None
