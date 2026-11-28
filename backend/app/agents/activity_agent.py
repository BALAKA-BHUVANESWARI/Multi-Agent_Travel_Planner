"""Activity agent: ranks sights and finds places to eat."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.agents.common import agent_failure, in_fanout, llm_note
from app.core import config
from app.core import security as guardrails
from app.core.utils import clip
from app.data.curated_destinations import place_name
from app.graph.state import entry
from app.observability import recorder as observe
from app.services import fact_checks
from app.services import group_service as group_mod
from app.services import sights_guide as guide
from app.services.feedback_parser import matches_excluded
from app.tools.client import call_with_retry
from app.tools.errors import ToolError

RANK_COST_SCALE = {"normal": 3000.0, "cheaper": 800.0, "cheapest": 300.0}
_SLOTS = {"morning", "afternoon", "evening", "any"}


def _position(p: dict) -> dict:
    lat, lon = p.get("lat"), p.get("lon")
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)) \
            and -90 <= lat <= 90 and -180 <= lon <= 180:
        return {"lat": float(lat), "lon": float(lon)}
    return {}


def _clean_candidate(p: dict) -> dict | None:
    try:
        cost, hours = int(p["cost"]), float(p["hours"])
        if cost < 0 or hours <= 0 or p["slot"] not in _SLOTS:
            return None
        return {"id": str(p["id"])[:40], "name": guardrails.sanitize_untrusted(p["name"], 90),
                "tags": [str(t) for t in p.get("tags", [])][:6], "outdoor": bool(p["outdoor"]),
                "cost": cost, "hours": hours, "slot": p["slot"],
                "desc": guardrails.sanitize_untrusted(p.get("desc", ""), 160),
                **({"far": True} if p.get("far") is True else {}),
                **_position(p),
                **({"kind": str(p["kind"])[:20]} if isinstance(p.get("kind"), str) else {}),
                **({"fame": float(p["fame"])} if isinstance(p.get("fame"), (int, float)) else {})}
    except (KeyError, TypeError, ValueError):
        return None


def rank_candidates(cands: list[dict], prefs: list[str], strategy: str, food_boost: bool = False) -> list[dict]:
    """Hard filter by the strategy's per-person cost cap, then score by preference match,
    popularity (catalog order) and cost."""
    cap = config.ACTIVITY_COST_CAP[strategy]
    pool = [c for c in cands if cap is None or c["cost"] <= cap]
    n = max(1, len(cands))
    scored = []
    for idx, c in enumerate(pool):
        match = sum(1 for t in c["tags"] if t in prefs)
        if food_boost and "food" in c["tags"]:
            match += 1
        score = 3 * match + (n - idx) / n * 2 - c["cost"] / RANK_COST_SCALE[strategy] - (2.5 if c.get("far") else 0)
        scored.append((score, idx, {**c, "score": round(score, 3)}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s[2] for s in scored]


_RERANK_SCHEMA = {"type": "object", "required": ["order"],
                  "properties": {"order": {"type": "array", "items": {"type": "string"}, "maxItems": 40}}}


def _llm_rerank(ranked: list[dict], c: dict, deps) -> tuple[list[dict], bool]:
    if not deps.llm or not deps.llm.available("activities") or len(ranked) < 3:
        return ranked, False
    import json
    system = ("You re-rank candidate travel activities for a traveler, best first, using their stated "
              "preferences. Candidates marked far are day trips several km out of town: rank them after "
              "the nearby sights unless nothing nearby fits. Return only ids that appear in the candidates list.")
    user = json.dumps({"preferences": c["preferences"], "travelers": c["travelers"],
                       "candidates": [{"id": r["id"], "name": r["name"], "tags": r["tags"], "cost": r["cost"],
                                       **({"far": True} if r.get("far") else {})} for r in ranked]})
    obj = deps.llm.complete_json("activities", system, user, _RERANK_SCHEMA)
    if not obj:
        return ranked, False
    by_id = {r["id"]: r for r in ranked}
    unknown = [i for i in obj["order"] if i not in by_id]
    observe.event("guardrail", "ai_ranking_ids", "rejected" if unknown else "ok", detail=unknown or None,
                  unknown=len(unknown), returned=len(obj["order"]), offered=len(ranked))
    fact_checks.record_ranking(len(obj["order"]), unknown)
    seen, order = set(), []
    for i in obj["order"]:
        if i in by_id and i not in seen:
            seen.add(i); order.append(by_id[i])
    if not order:
        return ranked, False
    full = order + [r for r in ranked if r["id"] not in seen]
    # Hard rule stays in code: whatever order the LLM chose, far day trips come after nearby sights.
    return [r for r in full if not r.get("far")] + [r for r in full if r.get("far")], True


DINING_WAIT = 25.0          # seconds the activities agent waits for the restaurant lookup


def _dining_result(future) -> dict:
    """The restaurant lookup, cleaned. Never raises: a failed lookup just means no restaurant section."""
    empty = {"veg": [], "nonveg": [], "other": [], "data_quality": "none", "attribution": [], "note": ""}
    try:
        res = future.result(timeout=DINING_WAIT)
    except Exception as e:                                       # noqa: BLE001 - dining must never break a plan
        observe.event("retrieval_wait", "restaurants", "gave_up", error=type(e).__name__)
        return {**empty, "note": f"Restaurant lookup unavailable ({guardrails.sanitize_untrusted(str(e), 80)})."}
    if not isinstance(res, dict):
        return empty

    def clean(items, n):
        out = []
        for it in (items or [])[:n]:
            if not isinstance(it, dict) or not it.get("name"):
                continue
            out.append({"name": guardrails.sanitize_untrusted(str(it["name"]), 70),
                        "serves": it.get("serves") if it.get("serves") in ("veg", "both", "nonveg", "unknown") else "unknown",
                        "cuisine": guardrails.sanitize_untrusted(str(it.get("cuisine") or ""), 50),
                        "hours": guardrails.sanitize_untrusted(str(it.get("hours") or ""), 90),
                        "hours_known": bool(it.get("hours_known")),
                        "best_time": guardrails.sanitize_untrusted(str(it.get("best_time") or ""), 90),
                        "desc": guardrails.sanitize_untrusted(str(it.get("desc") or ""), 140),
                        "source": it.get("source") if it.get("source") in ("osm", "wikivoyage") else ""})
        return out
    return {"veg": clean(res.get("veg"), 6), "nonveg": clean(res.get("nonveg"), 6), "other": clean(res.get("other"), 4),
            "data_quality": str(res.get("data_quality") or "none")[:30],
            "attribution": [str(a)[:120] for a in (res.get("attribution") or [])][:4],
            "note": guardrails.sanitize_untrusted(str(res.get("note") or ""), 400)}


def _data_quality_warning(quality: str | None, name: str) -> list[str]:
    if quality == "osm":
        return [f"Sights for {name} come from open data (OpenStreetMap, Wikipedia, Wikivoyage). Entry fees are rough estimates based on "
                "the type of place and the country's price level; check opening times and prices before you go."]
    if quality == "generic":
        return [f"Detailed place data for {name} could not be loaded, so the day plans use generic suggestions "
                "(walking tour, market, dinner). Try again later to get named sights."]
    return []


def activities_node(state: dict, deps) -> dict:
    if not in_fanout(state, "activities"):
        return {}
    c = state["constraints"]
    pool = ThreadPoolExecutor(max_workers=1)                    # restaurants are looked up while the sights are
    f_dine = pool.submit(observe.carry(call_with_retry), deps.tools, "search_dining", retries=1, sleep=deps.sleep,
                         destination=c["destination"], destination_geo=c.get("destination_geo"))
    pool.shutdown(wait=False)
    try:
        res = call_with_retry(deps.tools, "search_places", sleep=deps.sleep, destination=c["destination"],
                              preferences=c["preferences"], destination_geo=c.get("destination_geo"))
        cands = [x for x in (_clean_candidate(p) for p in res["candidates"]) if x]
        if not cands:
            raise ValueError("no usable places returned")
    except (ToolError, KeyError, ValueError) as e:
        out = agent_failure("activities", "activities", e, "Places lookup")
        out["activities"] = {"error": str(e), "candidates": [], "tips": [], "nearby": []}
        return out
    excluded = state.get("excluded") or []
    if excluded:                                                 # "skip water sports" is a hard rule
        cands = [x for x in cands if not any(matches_excluded(x, t) for t in excluded)]
    ranked = rank_candidates(cands, c["preferences"], state["strategy"], state.get("food_boost", False))
    ranked, used_llm = _llm_rerank(ranked, c, deps)
    ranked = group_mod.fair_order(ranked, state.get("group") or [])
    tips = [{"text": clip(guardrails.sanitize_untrusted(t["text"], 600), 300), "source": t.get("source", "")}
            for t in res.get("tips", [])]
    nearby = [{"name": guardrails.sanitize_untrusted(n["name"], 80), "kind": n.get("kind", "")}
              for n in res.get("nearby", [])]
    quality = res.get("data_quality")
    notes = _data_quality_warning(quality, place_name(c, "destination"))
    dine = _dining_result(f_dine)
    attribution = list(dict.fromkeys(list(res.get("attribution", [])) + dine["attribution"]))
    out = {"activities": {"candidates": ranked, "tips": tips, "nearby": nearby, "estimated": True,
                          "attribution": attribution, "llm_reranked": used_llm,
                          "data_quality": quality, "top_sights": guide.top_sights(cands),
                          "top_sights_note": guide.NOTE, "dining": dine, "notices": notes}, "warnings": notes,
            "log": [entry("activities", f"{len(ranked)} candidates for strategy '{state['strategy']}'"
                                        + (" (LLM re-ranked)" if used_llm else "")
                                        + llm_note(deps, "activities", used_llm)
                                        + (f" [{quality} data]" if quality and quality != "curated" else ""))]}
    return out
