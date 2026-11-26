"""One-off probe of the live-price providers. Run it yourself after adding a key (or both keys) to .env:

    python -m travel_planner.tools.live_probe            # round 1: both providers, 4 + 6 requests
    python -m travel_planner.tools.live_probe round2     # round 2: Tavily only, 4 page reads (about 8 credits)

Round 1 tests whichever providers have keys:
  * Bright Data SERP API (BRIGHTDATA_API_KEY + BRIGHTDATA_SERP_ZONE): 4 requests, about 4 of 5,000 free records.
  * Tavily (TAVILY_API_KEY): 6 requests, about 8 of 1,000 free credits (search = 1, advanced extract = 2).
Round 2 follows up on what round 1 showed: flights for ANY pair of places typed as text (no airport codes needed)
and hotel prices in rupees for the trip dates.

Every raw answer is saved in ./live_probe/ and one summary line per request is printed (and saved in
live_probe/summary.txt, or summary_round2.txt). The summary counts rupee prices and, for page reads, flights found,
which is the quick way to see what is usable. Keys are never printed or saved. Send the summary file (and, if asked,
the other files) back so the real response layout can be parsed; nothing in them is secret.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from .. import config
from . import gflights
from .live_flights import economy_with_price, parse_google_flights

ENDPOINT = "https://api.brightdata.com/request"
TAVILY_SEARCH = "https://api.tavily.com/search"
TAVILY_EXTRACT = "https://api.tavily.com/extract"
MAX_BYTES = 400_000
OUT = Path("live_probe")

# Sites whose result snippets usually show a "from Rs X" price.
FLIGHT_SITES = ["makemytrip.com", "goibibo.com", "cleartrip.com", "ixigo.com", "skyscanner.co.in", "kayak.co.in",
                "easemytrip.com"]
HOTEL_SITES = ["booking.com", "makemytrip.com", "goibibo.com", "agoda.com", "tripadvisor.in", "cleartrip.com"]

_PRICE = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?\d[\d,]*", re.IGNORECASE)


def price_hits(text: str) -> int:
    """How many rupee prices (₹ 4,500 / Rs. 4500 / INR 4500) a piece of text mentions."""
    text = (text or "").replace("\\u20b9", "₹").replace("\\u20B9", "₹")          # JSON often escapes the rupee sign
    return len(_PRICE.findall(text))


def _post(url: str, body: dict, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:                  # noqa: S310
            return r.status, r.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")


def call(url: str, key: str, zone: str, timeout: float = 90.0) -> tuple[int, str]:
    """One Bright Data SERP API request for a Google URL."""
    return _post(ENDPOINT, {"zone": zone, "url": url, "format": "raw"}, {"Authorization": f"Bearer {key}"}, timeout)


def tavily_call(endpoint: str, payload: dict, key: str, timeout: float = 90.0) -> tuple[int, str]:
    """One Tavily request (search or extract)."""
    return _post(endpoint, payload, {"Authorization": f"Bearer {key}"}, timeout)


def variants(depart: str, ret: str) -> dict[str, str]:
    base = "&curr=INR&gl=in&hl=en"
    text = quote_plus(f"Flights from Delhi to Goa on {depart} through {ret}")
    return {
        "flights_tfs_json": gflights.flights_url((gflights.AIRPORT, "DEL"), (gflights.AIRPORT, "GOI"), depart, ret,
                                                 adults=2) + "&brd_json=1",
        "flights_tfs_raw": gflights.flights_url((gflights.AIRPORT, "DEL"), (gflights.AIRPORT, "GOI"), depart, ret,
                                                adults=2),
        "flights_text_json": f"https://www.google.com/travel/flights?q={text}{base}&brd_json=1",
        "hotels_json": f"https://www.google.com/travel/hotels?q={quote_plus('hotels in Jaipur')}{base}&brd_json=json",
    }


def tavily_requests(depart: str, ret: str) -> dict[str, tuple[str, dict]]:
    """name -> (endpoint, payload). Same two trips as the Bright Data probe: Delhi-Goa flights, Jaipur hotels."""
    search = {"search_depth": "basic", "max_results": 8, "include_answer": True}
    flights_url = gflights.flights_url((gflights.AIRPORT, "DEL"), (gflights.AIRPORT, "GOI"), depart, ret, adults=2)
    hotels_url = f"https://www.google.com/travel/hotels?q={quote_plus('hotels in Jaipur')}&curr=INR&gl=in&hl=en"
    return {
        "tavily_flights_search": (TAVILY_SEARCH, {
            "query": f"Delhi to Goa round trip flight price INR {depart} to {ret} 2 adults", **search}),
        "tavily_flights_sites": (TAVILY_SEARCH, {
            "query": f"Delhi to Goa flights {depart} price", "include_domains": FLIGHT_SITES, **search}),
        "tavily_hotels_search": (TAVILY_SEARCH, {
            "query": "best hotels in Jaipur price per night INR", **search}),
        "tavily_hotels_sites": (TAVILY_SEARCH, {
            "query": "hotels in Jaipur price per night", "include_domains": HOTEL_SITES, **search}),
        "tavily_flights_extract": (TAVILY_EXTRACT, {
            "urls": [flights_url], "extract_depth": "advanced", "timeout": 60}),
        "tavily_hotels_extract": (TAVILY_EXTRACT, {
            "urls": [hotels_url], "extract_depth": "advanced", "timeout": 60}),
    }


def tavily_round2_requests(depart: str, ret: str) -> dict[str, tuple[str, dict]]:
    """Round 2 (2 credits each). Flights typed as text so Google resolves any place; hotels with dates in the text."""
    base = "&curr=INR&gl=in&hl=en"
    page = {"extract_depth": "advanced", "timeout": 60}

    def flights(a: str, b: str) -> str:
        q = quote_plus(f"Flights from {a} to {b} on {depart} through {ret} for 2 adults")
        return f"https://www.google.com/travel/flights?q={q}{base}"

    hotels_q = quote_plus(f"hotels in Jaipur from {depart} to {ret} for 2 adults")
    return {
        "tavily2_flights_text_domestic": (TAVILY_EXTRACT, {"urls": [flights("Delhi", "Goa")], **page}),
        "tavily2_flights_text_abroad": (TAVILY_EXTRACT, {"urls": [flights("Mumbai", "Paris")], **page}),
        "tavily2_hotels_text_dates": (TAVILY_EXTRACT, {
            "urls": [f"https://www.google.com/travel/hotels?q={hotels_q}{base}"], **page}),
        "tavily2_hotels_currency_param": (TAVILY_EXTRACT, {
            "urls": [f"https://www.google.com/travel/hotels?q={quote_plus('hotels in Jaipur')}{base}&currency=INR"
                     f"&checkin={depart}&checkout={ret}&adults=2"], **page}),
    }


def describe_page(raw: str) -> str:
    """What a fetched Google Travel page holds: flights (count, cheapest economy fare) or hotel nightly prices."""
    parsed = parse_google_flights(raw)
    if parsed["flights"]:
        cheapest = economy_with_price(parsed)
        low = f", cheapest economy {cheapest[0]['currency']} {cheapest[0]['price']}" if cheapest else ""
        return f"{len(parsed['flights'])} flights ({parsed['adults']} adults, {parsed['currency']}){low}"
    nightly = len(re.findall(r"\bnightly\b", raw))
    symbols = {c: raw.count(c) for c in "₹$€£" if raw.count(c)}
    return f"{nightly} nightly hotel prices, currency signs {symbols or 'none'}" if nightly else ""


def describe_tavily(text: str) -> str:
    """Short facts about a Tavily answer: result count, answer present, rupee prices seen. '' if it is not JSON."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    results = data.get("results") or []
    with_price = sum(1 for r in results if isinstance(r, dict)
                     and price_hits(str(r.get("content", "")) + str(r.get("raw_content", ""))))
    parts = [f"{len(results)} results"]
    if "answer" in data:
        parts.append("answer " + ("with price" if price_hits(str(data["answer"])) else "no price"))
    if "failed_results" in data:
        parts.append(f"{len(data.get('failed_results') or [])} failed")
    parts.append(f"{with_price} mention a price")
    first = results[0] if results and isinstance(results[0], dict) else {}
    if first.get("raw_content") and first.get("title") and "url" in first and "google.com/travel" in first["url"]:
        parts.append(f"page '{str(first['title'])[:50]}'")
        page = describe_page(str(first["raw_content"]))
        if page:
            parts.append(page)
    return ", ".join(parts)


def _record(name: str, url_line: str, status: int, text: str, secrets: list[str], t0: float, lines: list[str],
            extra: str = "") -> None:
    for s in secrets:
        text = text.replace(s, "***")
    (OUT / f"{name}.txt").write_text(f"HTTP {status}\n{url_line}\n\n{text}", encoding="utf-8")
    line = (f"{name}: HTTP {status}, {len(text)} chars, {price_hits(text)} rupee prices"
            f"{', ' + extra if extra else ''}, {time.time() - t0:.1f} s -> live_probe/{name}.txt")
    print(line)
    lines.append(line)


def run_brightdata(key: str, zone: str, depart: str, ret: str, lines: list[str]) -> None:
    print("Bright Data: 4 requests")
    for name, url in variants(depart, ret).items():
        t0 = time.time()
        try:
            status, text = call(url, key, zone)
        except Exception as e:                                                   # noqa: BLE001 - report, keep going
            status, text = 0, f"{type(e).__name__}: {e}"
        hint = ("the zone name is wrong, or it is not a SERP API zone: use the short name of a zone created under "
                "Create an API > SERP API") if status == 400 and "zone" in text and "not found" in text else ""
        _record(name, f"URL {url}", status, text, [key], t0, lines, hint)


def run_tavily(key: str, depart: str, ret: str, lines: list[str], round2: bool = False) -> None:
    requests = (tavily_round2_requests if round2 else tavily_requests)(depart, ret)
    print(f"Tavily: {len(requests)} requests")
    for name, (endpoint, payload) in requests.items():
        t0 = time.time()
        try:
            status, text = tavily_call(endpoint, payload, key)
        except Exception as e:                                                   # noqa: BLE001 - report, keep going
            status, text = 0, f"{type(e).__name__}: {e}"
        _record(name, f"ENDPOINT {endpoint}\nREQUEST {json.dumps(payload)}", status, text, [key], t0, lines,
                describe_tavily(text))


def main(argv: list[str] | None = None) -> int:
    round2 = "round2" in (argv or [])
    config.load_env()
    bd_key, zone = os.environ.get("BRIGHTDATA_API_KEY", "").strip(), os.environ.get("BRIGHTDATA_SERP_ZONE", "").strip()
    tv_key = os.environ.get("TAVILY_API_KEY", "").strip()
    have_bd, have_tv = bool(bd_key and zone) and not round2, bool(tv_key)
    if round2 and not have_tv:
        print("Round 2 uses Tavily: set TAVILY_API_KEY in .env first (see .env.example).")
        return 2
    if not (have_bd or have_tv):
        print("Set BRIGHTDATA_API_KEY and BRIGHTDATA_SERP_ZONE, and/or TAVILY_API_KEY, in .env first "
              "(see .env.example).")
        return 2
    today = date.today()
    depart, ret = (today + timedelta(days=30)).isoformat(), (today + timedelta(days=34)).isoformat()
    OUT.mkdir(exist_ok=True)
    lines: list[str] = []
    if have_bd:
        run_brightdata(bd_key, zone, depart, ret, lines)
    elif not round2:
        print("Bright Data: skipped (BRIGHTDATA_API_KEY / BRIGHTDATA_SERP_ZONE not set).")
    if have_tv:
        run_tavily(tv_key, depart, ret, lines, round2)
    else:
        print("Tavily: skipped (TAVILY_API_KEY not set).")
    name = "summary_round2.txt" if round2 else "summary.txt"
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Done. Send live_probe/{name} (or paste the lines above); the other files only if asked.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
