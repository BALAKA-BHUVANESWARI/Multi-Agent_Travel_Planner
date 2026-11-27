"""Dependency-free runner: executes the SAME nodes and routers as the LangGraph graph.

Used for tests, the CLI, the stdlib dev server, and as an automatic fallback when
LangGraph is not installed. Parallel fan-out uses a thread pool; the human approval
step "interrupts" by persisting state and returning, and ``resume`` continues from
the SQLite checkpoint (so it survives a process restart).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.core.tracing import wrap
from app.graph import edges as routing
from app.graph.deps import Deps
from app.graph.nodes import NODES, WORKERS, approval_node
from app.graph.state import apply_update, entry, initial_state
from app.observability import recorder as observe

MAX_STEPS = 25          # hard stop against runaway loops (the real caps are 2 replans + 2 revisions)


class Planner:
    def __init__(self, deps: Deps | None = None, nodes: dict | None = None, max_workers: int = 4):
        self.deps = deps or Deps.default()
        self.max_workers = max_workers
        n = dict(NODES)
        n.update(nodes or {})                      # tests can swap in faulty nodes
        self.nodes = {name: wrap(name, fn) for name, fn in n.items()}

    # ------------------------------------------------------------ internals
    def _step(self, state: dict, name: str) -> dict:
        return apply_update(state, self.nodes[name](state, self.deps))

    def _fanout(self, state: dict) -> dict:
        """Run the 4 workers concurrently against the same input state; merge their disjoint writes."""
        snapshot = dict(state)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {w: pool.submit(observe.carry(self.nodes[w]), snapshot, self.deps) for w in WORKERS}
            updates = {w: f.result() for w, f in futures.items()}
        for w in WORKERS:                   # deterministic merge order
            state = apply_update(state, updates[w])
        return state

    def _save(self, state: dict) -> dict:
        self.deps.store.save_state(state["thread_id"], state)
        return state

    def _plan_loop(self, state: dict) -> dict:
        """supervisor -> fan-out -> merge -> budget -> critic, with conditional replans."""
        for _ in range(MAX_STEPS):
            state = self._step(state, "supervisor")
            state = self._fanout(state)
            state = self._step(state, "merge")
            state = self._step(state, "budget")
            if routing.after_budget(state) == "supervisor":
                continue
            state = self._step(state, "critic")
            if routing.after_critic(state) == "supervisor":
                continue
            break
        else:
            state = apply_update(state, {"warnings": ["Stopped: internal step limit reached."],
                                         "log": [entry("runner", "MAX_STEPS hit")]})
        return self._step(state, "present")

    # ----------------------------------------------------------- public API
    def start(self, request: str, thread_id: str | None = None, group: list | None = None,
              memory: dict | None = None) -> dict:
        state = initial_state(request, thread_id, group, memory)
        state = self._step(state, "guardrail")
        if routing.after_guardrail(state) == "end":
            return self._save(state)
        state = self._step(state, "intake")
        if routing.after_intake(state) == "end":
            return self._save(state)
        return self._save(self._plan_loop(state))

    def resume(self, thread_id: str, decision: dict) -> dict:
        state = self.deps.store.load_state(thread_id)
        if state is None:
            raise KeyError(f"unknown thread '{thread_id}'")
        if state.get("status") in ("booked", "cancelled"):
            return state                            # already finished: resuming again is a no-op
        if state.get("status") != "awaiting_approval":
            raise ValueError(f"thread is '{state.get('status')}', not awaiting approval")
        state = apply_update(state, approval_node(state, decision, self.deps))
        for _ in range(MAX_STEPS):
            nxt = routing.after_approval(state)
            if nxt == "end":
                break
            if nxt == "book":
                state = self._step(state, "book")
                if routing.after_book(state) == "writer":
                    state = self._step(state, "writer")
                    break
                state = self._step(state, "present")
                break
            if nxt == "supervisor":
                state = self._plan_loop(state)
                break
            state = self._step(state, "present")     # feedback not understood / no-op: ask again
            break
        return self._save(state)

    def get(self, thread_id: str) -> dict | None:
        return self.deps.store.load_state(thread_id)

    def delete(self, thread_id: str) -> None:
        self.deps.store.delete_trip(thread_id)

    # ---------------------------------------------------------- evaluation
    def evaluate(self, constraints: dict, strategy: str, food_boost: bool = False) -> dict:
        """Run one plan pass for a given strategy and return the budget report (no replans, no save).
        Handy for tests and evals: 'what would this trip cost on each strategy?'"""
        state = initial_state("evaluate")
        state.update(constraints=constraints, strategy=strategy, status="running", food_boost=food_boost,
                     fanout=list(WORKERS))
        state = self._fanout(state)
        state = self._step(state, "merge")
        state = self._step(state, "budget")
        return state["budget_report"]
