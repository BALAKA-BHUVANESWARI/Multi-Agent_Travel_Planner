"""Open-Meteo client (no API key; non-commercial use; attribution required).

Forecast when the whole trip is inside the 16-day horizon, otherwise a
historical-climate estimate built from the same dates in the last 3 years.
``fetch`` is injectable so tests never touch the network.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Callable

from .. import config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


def fetch_json(url: str, params: dict, timeout: float = 6.0) -> dict:
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "travel-planner-demo/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (fixed https hosts)
        return json.loads(r.read().decode("utf-8"))


def choose_mode(start: date, days: int, today: date) -> str:
    """'forecast' if the whole trip falls within the forecast window, else 'climate'."""
    end = start + timedelta(days=days - 1)
    if start >= today and (end - today).days <= config.FORECAST_WINDOW_DAYS:
        return "forecast"
    return "climate"


def _day(d: date, tmax, tmin, prob) -> dict:
    prob = int(round(prob if prob is not None else 0))
    return {"date": d.isoformat(), "tmax": round(tmax, 1) if tmax is not None else None,
            "tmin": round(tmin, 1) if tmin is not None else None,
            "precip_prob": prob, "rainy": prob >= config.RAIN_THRESHOLD}


def forecast(lat: float, lon: float, start: date, days: int, fetch: Callable = fetch_json,
             timezone: str = "Asia/Kolkata") -> list[dict]:
    end = start + timedelta(days=days - 1)
    data = fetch(FORECAST_URL, {
        "latitude": lat, "longitude": lon, "timezone": timezone,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    daily = data["daily"]
    out = []
    for i, ds in enumerate(daily["time"]):
        out.append(_day(date.fromisoformat(ds), daily["temperature_2m_max"][i],
                        daily["temperature_2m_min"][i], daily["precipitation_probability_max"][i]))
    if len(out) != days:
        raise ValueError("forecast returned unexpected number of days")
    return out


def _shift_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:                        # Feb 29
        return d.replace(year=d.year - years, day=28)


def climate(lat: float, lon: float, start: date, days: int, years: int = 3,
            fetch: Callable = fetch_json, timezone: str = "Asia/Kolkata") -> list[dict]:
    """Rain probability = share of rainy (>=1 mm) days in a +/-3 day window over past years."""
    window = 3
    samples: dict[int, list[tuple]] = {i: [] for i in range(days)}
    for y in range(1, years + 1):
        s = _shift_years(start - timedelta(days=window), y)
        e = _shift_years(start + timedelta(days=days - 1 + window), y)
        data = fetch(ARCHIVE_URL, {
            "latitude": lat, "longitude": lon, "timezone": timezone,
            "start_date": s.isoformat(), "end_date": e.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        })
        daily = data["daily"]
        times = [date.fromisoformat(t) for t in daily["time"]]
        base = _shift_years(start, y)
        for i in range(days):
            centre = base + timedelta(days=i)
            for j, t in enumerate(times):
                if abs((t - centre).days) <= window:
                    samples[i].append((daily["temperature_2m_max"][j], daily["temperature_2m_min"][j],
                                       daily["precipitation_sum"][j]))
    out = []
    for i in range(days):
        rows = [r for r in samples[i] if r[0] is not None and r[2] is not None]
        if not rows:
            raise ValueError("no climate samples")
        tmax = sum(r[0] for r in rows) / len(rows)
        tmin = sum(r[1] for r in rows) / len(rows)
        prob = 100.0 * sum(1 for r in rows if r[2] >= 1.0) / len(rows)
        out.append(_day(start + timedelta(days=i), tmax, tmin, prob))
    return out
