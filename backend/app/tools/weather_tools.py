"""Tool: weather forecast or climate average."""
from __future__ import annotations

from datetime import date, timedelta

from app.core import config
from app.core.utils import hash01
from app.integrations import openmeteo
from app.tools.common import destination_info, parse_date


def _climate_estimate(slug: str, d: dict, start: date, days: int) -> list[dict]:
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        m = day.month - 1
        base = d["rain"][m]
        jitter = (hash01("wx", slug, day.isoformat()) - 0.5) * 30
        prob = int(max(0, min(100, round(base + jitter))))
        tj = (hash01("wxt", slug, day.isoformat()) - 0.5) * 3
        out.append({"date": day.isoformat(), "tmax": round(d["tmax"][m] + tj, 1),
                    "tmin": round(d["tmin"][m] + tj, 1), "precip_prob": prob,
                    "rainy": prob >= config.RAIN_THRESHOLD})
    return out


def get_weather(destination: str, start_date: str, days: int, today: str,
                destination_geo: dict | None = None) -> dict:
    d = destination_info(destination, destination_geo)
    start, tdy = parse_date(start_date), parse_date(today)
    mode = openmeteo.choose_mode(start, days, tdy)
    tz = {"timezone": "auto"} if d.get("dynamic") else {}
    if config.real_data_enabled():
        try:
            rows = (openmeteo.forecast(d["lat"], d["lon"], start, days, **tz) if mode == "forecast"
                    else openmeteo.climate(d["lat"], d["lon"], start, days, **tz))
            return {"mode": mode, "source": "open-meteo " + ("forecast" if mode == "forecast"
                    else "historical climate (last 3 years)"), "estimated": mode == "climate",
                    "attribution": openmeteo.ATTRIBUTION, "days": rows}
        except Exception:                      # network / parse failure -> offline estimate
            pass
    note = ("Offline estimate from curated monthly climate averages" if not d.get("dynamic")
            else "Rough offline estimate from latitude and month (live weather was unreachable)")
    return {"mode": mode, "source": "offline climate estimate", "estimated": True, "offline_fallback": True,
            "attribution": note, "days": _climate_estimate(destination, d, start, days)}
