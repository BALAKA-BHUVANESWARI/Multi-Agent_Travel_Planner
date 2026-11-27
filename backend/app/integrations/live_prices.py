"""Live flight and hotel prices: Google Flights / Google Hotels pages, read through Tavily Extract.

Why this way: no free flight or hotel API exists. Tavily's page reader returns what a visitor sees on Google's travel
pages (checked on 2026-11-25), and ``live_flights`` / ``live_hotels`` turn that text into numbers. Everything here is
best effort: any failure raises ``LiveUnavailable`` with a plain reason, and the caller falls back to the clearly
labelled estimate, so a plan is never blocked by this module.

Cost control: a page read costs 2 Tavily credits. Pages are cached for ``LIVE_CACHE_HOURS`` (default 3) and a daily
cap (``LIVE_DAILY_CREDITS``, default 30 of the free plan's ~33 a day) stops runaway spending; a replan that picks a
cheaper option re-uses the cached page and costs nothing.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

from app.core import cache, config
from app.integrations import google_flights_url as gflights
from app.integrations.google_flights import economy_with_price, parse_google_flights
from app.integrations.google_hotels import parse_google_hotels, stay_label
from app.observability import recorder as observe

TAVILY_EXTRACT = "https://api.tavily.com/extract"
FX_URL = "https://api.frankfurter.dev/v2/rate/{code}/INR"
CREDITS_PER_PAGE = 2
MAX_PAGE_CHARS = 400_000
SOURCE_FLIGHTS = "Google Flights via Tavily"
SOURCE_HOTELS = "Google Hotels via Tavily"
RETURN_DEPART = "17:00"           # Google shows no return times until an outbound flight is chosen
RETURN_NOTE = ("Return flight time is not shown by Google until you pick the outbound flight, so the plan assumes "
               "a late-afternoon departure (about 17:00). Check it before you book.")

# IATA codes of the places the planner already knows. Any other place is searched by name (Google picks the airport).
IATA = {"delhi": "DEL", "mumbai": "BOM", "bengaluru": "BLR", "hyderabad": "HYD", "chennai": "MAA", "kolkata": "CCU",
        "pune": "PNQ", "ahmedabad": "AMD", "lucknow": "LKO", "goa": "GOI", "jaipur": "JAI", "manali": "KUU",
        "kochi": "COK", "udaipur": "UDR"}

_lock = threading.Lock()


class LiveUnavailable(Exception):
    """Live prices could not be had; the message is a short reason that is safe to show the user.
    ``code`` is the same reason as a fixed word, for the records."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- network
def _post(url: str, body: dict, key: str, timeout: float = 90.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:                  # noqa: S310
            return r.status, r.read(5_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")


def _get_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": config.HTTP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:                      # noqa: S310
        return json.loads(r.read(200_000).decode("utf-8", "replace"))


def _tidy(raw: str) -> str:
    """Drop link targets and image tags: five times smaller, and nothing the parsers need is lost."""
    raw = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)
    return re.sub(r"\]\(https?://[^)]*\)", "]()", raw)[:MAX_PAGE_CHARS]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_page(url: str) -> str:
    key = config.tavily_key()
    if not key:
        raise LiveUnavailable("no Tavily key is set", "no_key")
    try:
        status, text = _post(TAVILY_EXTRACT, {"urls": [url], "extract_depth": "advanced", "timeout": 60}, key)
    except Exception as e:                                                       # noqa: BLE001
        raise LiveUnavailable(f"Tavily could not be reached ({type(e).__name__})", "tavily_unreachable") from None
    if status in (401, 403):
        raise LiveUnavailable("Tavily rejected the key (check TAVILY_API_KEY)", "tavily_rejected_key")
    if status in (402, 429, 432, 433):
        raise LiveUnavailable("Tavily is rate limiting or the plan's credits are used up", "tavily_limit")
    if status != 200:
        raise LiveUnavailable(f"Tavily answered HTTP {status}", "tavily_http_error")
    try:
        results = json.loads(text).get("results") or []
        raw = results[0]["raw_content"] if results else ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raw = ""
    return _tidy(raw or "")


# ----------------------------------------------------------------------- cache + cap
def _usage_key() -> str:
    return f"live-credits:{date.today().isoformat()}"


def credits_used_today() -> int:
    used = cache.get(_usage_key(), ttl=2 * 24 * 3600, record=False)          # a counter, not a looked-up page
    return int(used) if isinstance(used, (int, float)) else 0


def _reserve(credits: int = CREDITS_PER_PAGE) -> None:
    cap = config.live_daily_credits()
    with _lock:
        used = credits_used_today()
        if used + credits > cap:
            raise LiveUnavailable(f"today's live-price limit ({cap} Tavily credits) is used up", "daily_limit")
        cache.put(_usage_key(), used + credits)


@observe.retrieval("live_prices.page", count=lambda result: 1)
def get_page(url: str, ok, attempts: int = 2) -> tuple[str, str, bool]:
    """(text, fetched_at, from_cache) of a page for which ``ok(text)`` is true. A page that loads without results
    (Google sometimes answers with an empty shell) is retried once and is never cached."""
    key = f"live-page:v1:{url}"
    ttl = config.live_cache_hours() * 3600
    if ttl > 0:
        hit = cache.get(key, ttl=ttl)
        if isinstance(hit, dict) and ok(hit.get("text", "")):
            return hit["text"], hit.get("fetched_at", ""), True
    for attempt in range(max(1, attempts)):
        try:
            _reserve()
        except LiveUnavailable as e:
            if not attempt:              # nothing was read: not a failed lookup, one the planner chose not to make
                observe.current_span().fail("skipped", reason=e.code)
            else:
                observe.current_span().set(reason=e.code)
            raise
        observe.current_span().add("page_reads")
        observe.current_span().add("credits", CREDITS_PER_PAGE)
        try:
            text = _read_page(url)
        except LiveUnavailable as e:
            observe.current_span().set(reason=e.code)
            raise
        if ok(text):
            fetched = _now()
            if ttl > 0:
                cache.put(key, {"text": text, "fetched_at": fetched})
            return text, fetched, False
    observe.current_span().set(reason="no_results_on_page")
    raise LiveUnavailable("the Google page came back without any results", "no_results_on_page")


@observe.retrieval("live_prices.exchange_rate", count=lambda result: 1)
def rate_to_inr(code: str) -> tuple[float, str]:
    """(rupees per 1 unit of ``code``, the rate's date). Cached for 12 hours."""
    code = code.upper()
    if code == "INR":
        return 1.0, ""
    key = f"fx:v1:{code}"
    hit = cache.get(key, ttl=12 * 3600)
    if isinstance(hit, dict) and hit.get("rate"):
        return float(hit["rate"]), str(hit.get("date", ""))
    try:
        data = _get_json(FX_URL.format(code=code))
        rate = float(data["rate"] if "rate" in data else data["rates"]["INR"])
        asof = str(data.get("date", ""))
    except Exception:                                                            # noqa: BLE001
        raise LiveUnavailable(f"the {code} to INR exchange rate could not be fetched") from None
    if not 0.01 < rate < 100_000:
        raise LiveUnavailable(f"the {code} to INR exchange rate looked wrong")
    cache.put(key, {"rate": rate, "date": asof})
    return rate, asof


# ------------------------------------------------------------------------- flights
def flights_url(origin: str, dest: str, origin_name: str, dest_name: str, dep: date, ret: date, adults: int) -> str:
    """A search link Google resolves: by airport code when both places are known, otherwise by name."""
    o, d = IATA.get(origin), IATA.get(dest)
    if o and d:
        return gflights.flights_url((gflights.AIRPORT, o), (gflights.AIRPORT, d), dep.isoformat(), ret.isoformat(),
                                    adults)
    who = f"{adults} adult" + ("s" if adults != 1 else "")
    q = quote_plus(f"Flights from {origin_name} to {dest_name} on {dep.isoformat()} through {ret.isoformat()} "
                   f"for {who}")
    return f"https://www.google.com/travel/flights?q={q}&curr=INR&gl=in&hl=en"


def _hhmm_plus(clock: str, minutes: int) -> str:
    h, m = (int(x) for x in clock.split(":"))
    t = (h * 60 + m + minutes) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def _stops_text(f: dict) -> str:
    if f["stops"] == 0:
        return "nonstop"
    via = f" via {', '.join(f['via'])}" if f["via"] else ""
    return f"{f['stops']} stop{'s' if f['stops'] != 1 else ''}{via}"


def _flight_option(opt_id: str, f: dict, adults: int) -> dict:
    pp = int(round(f["price"] / adults))
    return {"id": opt_id, "label": f"{f['airline']}, {_stops_text(f)}: out {f['depart']} → {f['arrive']}",
            "stops": f["stops"], "duration_h": round(f["duration_min"] / 60, 1), "mode": "flight",
            "depart_out": f["depart"], "arrive_out": f["arrive"], "depart_back": RETURN_DEPART,
            "arrive_back": _hhmm_plus(RETURN_DEPART, f["duration_min"]), "price_pp": pp, "estimated": False,
            "live": True, "airline": f["airline"], "route": f"{f['origin_code']}→{f['dest_code']}",
            "page_total": f["price"], "note": RETURN_NOTE}


def flights(origin: str, dest: str, origin_name: str, dest_name: str, dep: date, ret: date, travelers: int) -> dict:
    """Live round-trip fares for ``travelers`` adults (best / cheaper / cheapest, each a real listed flight)."""
    if not 1 <= travelers <= 9:
        raise LiveUnavailable("Google Flights prices 1 to 9 travellers")
    url = flights_url(origin, dest, origin_name, dest_name, dep, ret, travelers)
    text, fetched_at, cached = get_page(url, lambda t: bool(economy_with_price(parse_google_flights(t))))
    page = parse_google_flights(text)
    if page["adults"] != travelers:
        raise LiveUnavailable(f"Google priced {page['adults'] or 'an unknown number of'} adults, not {travelers}")
    if page["currency"] != "INR":
        raise LiveUnavailable(f"Google showed prices in {page['currency'] or 'an unknown currency'}, not rupees")
    day = f"{dep:%a, %b} {dep.day}"
    rows = [f for f in economy_with_price(page) if f["depart_day"] == day and f["arrive_day"] == day
            and f["price_kind"] in (None, "round trip")]
    if not rows:
        raise LiveUnavailable("no same-day economy fares for the requested date were listed")
    codes = {(f["origin_code"], f["dest_code"]) for f in rows}
    if len(codes) > 1:                                    # Google mixed airports: keep the most listed pair
        best_pair = max(codes, key=lambda c: sum(1 for f in rows if (f["origin_code"], f["dest_code"]) == c))
        rows = [f for f in rows if (f["origin_code"], f["dest_code"]) == best_pair]
    o, d = IATA.get(origin), IATA.get(dest)
    first = rows[0]
    if (o and first["origin_code"] != o) or (d and first["dest_code"] != d):
        raise LiveUnavailable("Google listed a different route than the one searched")
    # Google's own ranking puts its pick first; `economy_with_price` sorts by price, so recover the page order.
    page_order = [f for f in page["flights"] if f in rows]
    best = page_order[0]
    cheapest = rows[0]
    below = [f for f in rows if f["price"] < best["price"]]          # strictly cheaper than Google's pick, if any
    cheaper = next((f for f in below if f["stops"] == 0), None) or (below[0] if below else best)
    options = [_flight_option("best", best, travelers), _flight_option("early_late", cheaper, travelers),
               _flight_option("one_stop", cheapest, travelers)]
    return {"source": SOURCE_FLIGHTS, "estimated": False, "live": True, "fetched_at": fetched_at,
            "from_cache": cached, "route": options[0]["route"], "options": options,
            "price_basis": f"round trip, per person (Google's total for {travelers} adult"
                           f"{'s' if travelers != 1 else ''} divided by {travelers}; taxes and fees included)"}


# -------------------------------------------------------------------------- hotels
def hotels_url(dest_name: str, checkin: date, checkout: date) -> str:
    q = quote_plus(f"hotels in {dest_name} from {checkin.isoformat()} to {checkout.isoformat()} for 2 adults")
    return f"https://www.google.com/travel/hotels?q={q}&curr=INR&gl=in&hl=en"


def hotels(dest_name: str, checkin: date, nights: int) -> dict:
    """Live nightly room prices for the trip dates (normal / cheaper / cheapest, each a real listed hotel)."""
    checkout = checkin + timedelta(days=nights)
    url = hotels_url(dest_name, checkin, checkout)
    text, fetched_at, cached = get_page(url, lambda t: len(parse_google_hotels(t)["hotels"]) >= 3)
    page = parse_google_hotels(text)
    if stay_label(checkin, checkout) not in page["stays"]:
        raise LiveUnavailable("Google showed hotel prices for other dates")
    cards = [h for h in page["hotels"] if h["total"] is None or h["nights"] == nights]
    currencies = {h["currency"] for h in cards}
    if len(currencies) != 1 or len(cards) < 3:
        raise LiveUnavailable("the hotel list was too short or mixed currencies")
    code = currencies.pop()
    rate, asof = (1.0, "") if code == "INR" else rate_to_inr(code)
    for h in cards:                                       # taxes and fees included when Google shows the stay total
        per_night = (h["total"] / nights) if h["total"] else h["nightly"]
        h["inr"] = int(round(per_night * rate))
    pool = [h for h in cards if h["rating"] is None or h["rating"] >= 3.8]
    pool = sorted(pool if len(pool) >= 3 else cards, key=lambda h: h["inr"])
    picks = {"3star": pool[len(pool) // 2], "2star": pool[len(pool) // 4], "budget": pool[0]}
    options = []
    for tier, h in picks.items():
        facts = ", ".join(x for x in ((f"{h['stars']}-star" if h["stars"] else ""),
                                      (f"rated {h['rating']}" if h["rating"] else "")) if x)
        options.append({"id": tier, "tier": tier, "label": f"{h['name']}" + (f" ({facts})" if facts else ""),
                        "price_night_per_room": h["inr"], "estimated": False, "live": True, "name": h["name"],
                        "stars": h["stars"], "rating": h["rating"], "shown_in": code})
    note = (f"Google showed these prices in {code}; converted at {rate:g} INR per {code}"
            + (f" (rate of {asof})" if asof else "") + ".") if code != "INR" else ""
    return {"source": SOURCE_HOTELS, "estimated": False, "live": True, "fetched_at": fetched_at, "from_cache": cached,
            "options": options, "fx_note": note, "hotels_listed": len(page["hotels"]),
            "price_basis": "per room per night for 2 guests, taxes and fees included (Google's stay total divided "
                           "by nights)"}
