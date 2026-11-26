"""Weather agent: day-by-day forecast or climate average."""
from __future__ import annotations

from app.agents.common import agent_failure, in_fanout
from app.graph.state import entry
from app.tools.client import call_with_retry
from app.tools.errors import ToolError


def weather_node(state: dict, deps) -> dict:
    if not in_fanout(state, "weather"):
        return {}
    c = state["constraints"]
    try:
        res = call_with_retry(deps.tools, "get_weather", sleep=deps.sleep, destination=c["destination"],
                              start_date=c["start_date"], days=c["days"], today=deps.today.isoformat(),
                              destination_geo=c.get("destination_geo"))
        if len(res["days"]) != c["days"]:
            raise ValueError("weather returned the wrong number of days")
    except (ToolError, KeyError, ValueError) as e:
        out = agent_failure("weather", "weather", e, "Weather lookup")
        out["weather"] = {"error": str(e), "days": []}
        return out
    rainy = sum(1 for d in res["days"] if d["rainy"])
    return {"weather": res, "log": [entry("weather", f"{res['source']}: {rainy}/{c['days']} rainy days")]}
