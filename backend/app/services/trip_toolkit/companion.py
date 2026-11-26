"""Travel Companion: a packing list built from this trip, local customs and useful information."""
from __future__ import annotations

import re

from app.data import country_facts as countries

INFO_NOTE = ("General reference information that can change. Check anything important, especially laws and "
             "medicine rules, with official sources before you travel.")
HOT_C, MILD_C, FREEZING_C = 30, 15, 5
_ON_WATER = re.compile(r"\b(water ?sports?|water|raft\w*|scuba|snorkel\w*|surf\w*|kayak\w*|canoe\w*|dive|diving)\b", re.I)


def _item(name: str, why: str = "") -> dict:
    return {"name": name, "why": why}


def _numbers(days: list[dict], key: str) -> list[float]:
    return [d[key] for d in days if isinstance(d.get(key), (int, float))]


def weather_summary(weather: dict | None) -> dict | None:
    days = (weather or {}).get("days") or []
    highs, lows = _numbers(days, "tmax"), _numbers(days, "tmin")
    if not highs or not lows:
        return None
    return {"high": max(highs), "low": min(lows), "rainy_days": sum(1 for d in days if d.get("rainy")),
            "estimated": bool((weather or {}).get("estimated", True))}


def _planned_tags(itinerary: dict | None) -> dict[str, list[str]]:
    """tag -> names of the planned activities that have it, in plan order."""
    out: dict[str, list[str]] = {}
    for day in (itinerary or {}).get("days", []):
        for item in day.get("items", []):
            if item.get("type") == "activity":
                for tag in item.get("tags") or []:
                    out.setdefault(tag, []).append(item.get("name", ""))
    return out


def _clothes(days: int, wx: dict | None) -> list[dict]:
    sets = min(days, 7)
    items = [_item(f"{sets} sets of tops and underwear",
                   "Plan to wash clothes on a longer trip." if days > 7 else f"For {days} days."),
             _item("2 pairs of trousers, skirts or shorts"), _item("Sleepwear")]
    if wx is None:
        items.append(_item("Layers for warm and cool weather", "No weather data was available: check a forecast."))
        return items
    if wx["high"] >= HOT_C:
        items.append(_item("Light, breathable clothes", f"Highs up to about {wx['high']:.0f}°C."))
    if wx["low"] < MILD_C:
        items.append(_item("Warm layer (fleece or jacket)", f"Lows down to about {wx['low']:.0f}°C."))
    if wx["low"] < FREEZING_C:
        items += [_item("Heavy jacket and thermals", "It can get close to freezing."),
                  _item("Warm cap, gloves and thick socks")]
    return items


def _weather_gear(wx: dict | None) -> list[dict]:
    items = []
    if wx and wx["rainy_days"]:
        why = f"Rain is likely on {wx['rainy_days']} day(s)."
        items += [_item("Umbrella or rain jacket", why), _item("Waterproof cover for phone and bag", why),
                  _item("Quick-dry clothes and spare footwear", why)]
    if wx and wx["high"] >= HOT_C:
        items += [_item("Sunscreen, sunglasses and a hat", "Hot days."),
                  _item("Oral rehydration salts", "Hot days.")]
    return items


def _activity_gear(tags: dict[str, list[str]], prefs: list[str]) -> list[dict]:
    items: dict[str, str] = {}                                       # item -> why (the first reason wins)

    def add(why: str, *names: str) -> None:
        for name in names:
            items.setdefault(name, why)

    adventures = tags.get("adventure", [])
    on_water = [n for n in adventures if _ON_WATER.search(n)]
    on_land = [n for n in adventures if n not in on_water]
    if "beach" in tags:
        add(f"For {tags['beach'][0]}.", "Swimwear and a quick-dry towel", "Flip-flops or sandals")
    if on_water:
        add(f"For {on_water[0]}.", "Swimwear and a quick-dry towel", "Waterproof pouch and a change of clothes")
    if on_land:
        add(f"For {on_land[0]}.", "Shoes with good grip", "Small daypack", "Insect repellent")
    if "nature" in tags:
        add(f"For {tags['nature'][0]}.", "Insect repellent")
    if "spiritual" in tags:
        add(f"Often expected at places of worship. Your plan includes {tags['spiritual'][0]}.",
            "Clothes that cover shoulders and knees")
        add("Many temples, mosques and gurdwaras ask you to take your shoes off.",
            "Footwear that is easy to take off, and socks")
    walking = tags.get("history") or tags.get("culture")
    if walking:
        add(f"For {walking[0]}.", "Comfortable walking shoes")
    if "nightlife" in tags:
        add("In case you go out in the evening.", "One smarter outfit")
    if "family" in prefs:
        add("If children are travelling.", "Snacks, a change of clothes and any child medicines")
    return [_item(name, why) for name, why in items.items()]


def _journey_gear(mode: str | None, option_label: str = "") -> list[dict]:
    drives = mode == "car" and "driver" not in option_label.lower()
    if mode == "flight":
        return [_item("Power banks and spare batteries in your hand baggage",
                      "Airlines do not allow them in checked bags."),
                _item("Liquids packed to your airline's cabin rules"),
                _item("Check-in done and the baggage allowance checked")]
    if mode in ("train", "ground"):
        return [_item("Small lock and chain for luggage"), _item("Water, snacks and a light blanket or shawl")]
    if mode == "bus":
        return [_item("Neck pillow and a warm layer", "Air-conditioned buses can be cold."),
                _item("Motion-sickness medicine if you need it")]
    if mode == "car":
        items = [_item("Offline maps, phone mount and car charger"), _item("Water and snacks for the road")]
        if drives:
            items.append(_item("Check spare tyre, jack and tool kit", "Do this before you set off."))
        return items
    if mode == "bike":
        return [_item("Helmet for rider and pillion"), _item("Riding jacket, gloves and sturdy boots"),
                _item("Rain gear and waterproof luggage covers"),
                _item("Puncture kit, basic tools and luggage straps"), _item("Offline maps and phone mount")]
    return []


def packing_list(constraints: dict, weather: dict | None, itinerary: dict | None, flight_sel: dict | None,
                 origin_cc: str, dest_cc: str) -> dict:
    days = int(constraints.get("days") or 2)
    wx = weather_summary(weather)
    international = bool(origin_cc and dest_cc and origin_cc != dest_cc)
    essentials = [
        _item("Photo ID and tickets", "See the Documents tab."),
        _item("Phone, charger and power bank"),
        _item("Your medicines with their prescriptions, and a small first-aid kit"),
        _item("Cards and some cash"),
        _item("Toothbrush and toiletries"),
        _item("Refillable water bottle"),
    ]
    abroad = []
    if international:
        abroad = [_item("Passport, plus a copy kept separately"),
                  _item("Card enabled for international use, and some foreign currency"),
                  _item("Roaming plan or local SIM")]
        facts = countries.useful_info(dest_cc)
        if facts:
            abroad.append(_item(f"Travel plug adapter (usual sockets: type {facts['plug_types']})",
                                "Compare with the plugs you use at home."))
        strict = dest_cc in countries.STRICT_MEDICINE
        abroad.append(_item("Check that your medicines are allowed",
                            "This country is strict about some ordinary medicines: check with its embassy."
                            if strict else "Some countries restrict common medicines."))
    groups = [("Essentials", essentials), ("Clothes", _clothes(days, wx)), ("Weather", _weather_gear(wx)),
              ("For your plans", _activity_gear(_planned_tags(itinerary), constraints.get("preferences") or [])),
              ("For the journey", _journey_gear((flight_sel or {}).get("mode"), (flight_sel or {}).get("label", ""))),
              ("Going abroad", abroad)]
    note = ""
    if wx and wx["estimated"]:
        note = ("Weather here is an estimate or a climate average, not a forecast: check the forecast a few days "
                "before you leave.")
    return {"groups": [{"title": t, "items": i} for t, i in groups if i], "weather": wx, "note": note}


def guide(constraints: dict, weather: dict | None, itinerary: dict | None, flight_sel: dict | None,
          origin_cc: str, dest_cc: str) -> dict:
    return {"packing": packing_list(constraints, weather, itinerary, flight_sel, origin_cc, dest_cc),
            "customs": countries.customs_for(dest_cc), "info": countries.useful_info(dest_cc),
            "info_note": INFO_NOTE}
