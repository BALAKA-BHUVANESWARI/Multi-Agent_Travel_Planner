import pytest

from travel_planner import config, guide
from travel_planner.rag import wikivoyage
from travel_planner.tools import dining, impl, osm

CENTER = {"lat": 15.335, "lon": 76.46}

WIKITEXT = """
{{eat | name=Green Leaf | content=Pure vegetarian thali, famous with locals. | hours=11:00-22:00 | url=http://x | lat=15.336 | long=76.461}}
{{eat | name=Sea Shack | content=Fresh seafood and grilled fish, a local favourite. | lat=15.33 | long=76.46}}
{{eat | name=Garden Cafe | content=Salads, pasta and vegan options, plus chicken wraps.}}
{{eat | name=Plain Diner | content=Good food.}}
{{eat | name=Far Away Grill | content=Steaks. | lat=15.9 | long=77.0}}
{{see | name=Not Food | content=A fort.}}
"""


def _els():
    return wikivoyage.parse_eat_listings(WIKITEXT)


def test_eat_listings_parse_hours_url_and_coordinates():
    els = _els()
    assert [e["tags"]["name"] for e in els] == ["Green Leaf", "Sea Shack", "Garden Cafe", "Plain Diner", "Far Away Grill"]
    g = els[0]["tags"]
    assert g["x_hours"] == "11:00-22:00" and g["x_url"] == "yes" and g["x_lat"] == 15.336


@pytest.mark.parametrize("name,text,tags,want", [
    ("Green Leaf", "Pure vegetarian thali", {}, "veg"),
    ("Bean Place", "", {"diet:vegetarian": "only"}, "veg"),
    ("Sunrise", "", {"cuisine": "vegetarian"}, "veg"),
    ("Sea Shack", "seafood and grilled fish", {}, "nonveg"),
    ("Steak House", "", {"cuisine": "steak_house"}, "nonveg"),
    ("Garden Cafe", "vegan options, plus chicken wraps", {}, "both"),
    ("Cafe", "", {"diet:vegetarian": "yes", "diet:vegan": "yes"}, "both"),
    ("Plain Diner", "Good food.", {}, "unknown"),
])
def test_diet_classification(name, text, tags, want):
    assert dining.classify(name, text, tags) == want


def test_dining_lists_are_split_ranked_and_timed():
    out = dining.build_dining(_els(), CENTER)
    veg = [r["name"] for r in out["veg"]]
    nonveg = [r["name"] for r in out["nonveg"]]
    assert veg[0] == "Green Leaf" and "Garden Cafe" in veg and "Sea Shack" not in veg
    assert "Sea Shack" in nonveg and "Garden Cafe" in nonveg and "Green Leaf" not in nonveg
    assert [r["name"] for r in out["other"]] == ["Plain Diner"]
    assert "Far Away Grill" not in veg + nonveg + [r["name"] for r in out["other"]]      # a day trip away
    g = out["veg"][0]
    assert g["hours"] == "11:00-22:00" and g["hours_known"] and g["best_time"]
    shack = out["nonveg"][0]
    assert not shack["hours_known"] and "not stated" in shack["hours"]                  # typical window, labelled


def test_osm_restaurants_use_diet_tags_and_rank_prominent_first():
    els = [{"type": "node", "id": 1, "lat": 15.34, "lon": 76.46,
            "tags": {"amenity": "restaurant", "name": "Veg Bhavan", "diet:vegetarian": "only",
                     "opening_hours": "Mo-Su 08:00-22:00", "website": "http://v", "wikidata": "Q1"}},
           {"type": "node", "id": 2, "lat": 15.34, "lon": 76.47,
            "tags": {"amenity": "restaurant", "name": "Kebab Corner", "cuisine": "kebab;grill"}},
           {"type": "way", "id": 3, "center": {"lat": 15.0, "lon": 76.0},
            "tags": {"amenity": "restaurant", "name": "Distant Dhaba", "cuisine": "indian"}}]
    out = dining.build_dining(els, CENTER)
    assert out["veg"][0]["name"] == "Veg Bhavan" and out["veg"][0]["hours"] == "Mo-Su 08:00-22:00"
    assert out["nonveg"][0]["name"] == "Kebab Corner" and out["nonveg"][0]["cuisine"] == "kebab, grill"
    assert "Distant Dhaba" not in str(out)


def test_search_dining_offline_and_live(monkeypatch):
    geo = {"slug": "hampi-in", "name": "Hampi", "lat": 15.335, "lon": 76.46, "cc": "IN", "cost_factor": 1.0,
           "population": 3000}
    off = impl.search_dining("hampi-in", geo)
    assert off["data_quality"] == "none" and off["veg"] == [] and "REAL_DATA" in off["note"]
    monkeypatch.setattr(config, "real_data_enabled", lambda: True)
    monkeypatch.setattr(wikivoyage, "eat_listings", lambda title, fetch=None: _els())
    monkeypatch.setattr(osm, "restaurant_elements", lambda lat, lon, r, post=None: [])
    on = impl.search_dining("hampi-in", geo)
    assert on["veg"][0]["name"] == "Green Leaf" and on["data_quality"] == "wikivoyage"
    assert "Wikivoyage" in " ".join(on["attribution"]) and "ratings" in on["note"]
    monkeypatch.setattr(wikivoyage, "eat_listings", lambda title, fetch=None: [])
    assert impl.search_dining("hampi-in", geo)["data_quality"] == "none"


# ------------------------------------------------------------------------------------------------ sights
def _c(i, name, tags, fame=None, slot="any", **kw):
    return {"id": f"x{i}", "name": name, "tags": tags, "slot": slot, "cost": 0, "desc": "", **kw,
            **({"fame": fame} if fame is not None else {})}


def test_top_sights_are_ranked_by_fame_with_labels_and_timings():
    cands = [_c(1, "Small Temple", ["spiritual"], fame=2), _c(2, "Hidden Falls", ["nature"], fame=5),
             _c(3, "Grand Fort", ["history"], fame=9), _c(4, "Day Trip Fort", ["history"], fame=10, far=True),
             {"id": "gen-walk", "name": "Old town walking tour", "tags": ["culture"], "slot": "morning", "cost": 0}]
    top = guide.top_sights(cands)
    assert [t["name"] for t in top] == ["Grand Fort", "Hidden Falls", "Small Temple"]     # far + generic left out
    assert [t["rank"] for t in top] == [1, 2, 3]
    by = {t["name"]: t for t in top}
    assert by["Grand Fort"]["label"] == "Historical" and "Early morning" in by["Grand Fort"]["best_time"]
    assert by["Hidden Falls"]["label"] == "Waterfall" and by["Hidden Falls"]["season"]
    assert by["Small Temple"]["label"] == "Spiritual"


def test_curated_destinations_rank_by_catalog_order():
    cands = [_c(1, "First", ["culture"]), _c(2, "Second", ["culture"]), _c(3, "Third", ["culture"])]
    assert [t["name"] for t in guide.top_sights(cands)] == ["First", "Second", "Third"]


def test_plan_carries_top_sights_and_dining_and_the_summary_lists_them(make):
    s = make().start("Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2")
    acts = s["activities"]
    assert acts["top_sights"] and acts["top_sights"][0]["rank"] == 1 and acts["top_sights"][0]["best_time"]
    assert acts["dining"]["veg"] == [] and acts["dining"]["note"]                        # offline: no restaurant data
    assert "## Top sights" in s["summary"] and "best " in s["summary"]
    assert "## Where to eat" not in s["summary"]                                          # nothing to list offline


def test_summary_lists_restaurants_when_data_exists(make):
    from travel_planner import agents
    s = make().start("Plan a 5 day trip to Goa from Delhi in December, budget 3 lakh for 2")
    s["activities"]["dining"] = {**dining.build_dining(_els(), CENTER), "note": dining.NOTE}
    text = agents.render_summary(s)
    assert "## Where to eat" in text and "**Vegetarian**" in text and "**Non-vegetarian**" in text
    assert "Green Leaf" in text and "Sea Shack" in text and "More places (menu not specified)" in text


def test_dining_text_from_a_tool_is_sanitised_by_the_agent():
    from concurrent.futures import Future
    from travel_planner import agents
    f = Future()
    f.set_result({"veg": [{"name": "Nice\x00Place", "serves": "veg", "desc": "x" * 500, "hours": "9-5",
                           "hours_known": True, "best_time": "noon", "source": "osm"},
                          {"name": "", "serves": "veg"}, "not a dict"],
                  "nonveg": [{"name": "Grill", "serves": "bogus"}], "other": [], "note": "n"})
    out = agents._dining_result(f)
    assert len(out["veg"]) == 1 and "\x00" not in out["veg"][0]["name"] and len(out["veg"][0]["desc"]) <= 140
    assert out["nonveg"][0]["serves"] == "unknown"


def test_plural_and_relaxed_cases():
    assert dining.classify("Mayura", "serves a buffet lunch for vegetarians") == "both"
    assert dining.classify("Annapurna", "pure vegetarians welcome") == "veg"


def test_osm_restaurants_fall_back_to_a_relaxed_query_for_small_places():
    queries = []

    def post(q):
        queries.append(q)
        if len(queries) == 1:
            return {"elements": [{"type": "node", "id": 1, "tags": {"name": "A", "amenity": "restaurant"}}]}
        return {"elements": [{"type": "node", "id": 1, "tags": {"name": "A", "amenity": "restaurant"}},
                             {"type": "node", "id": 2, "tags": {"name": "B", "amenity": "restaurant", "cuisine": "indian"}}]}
    els = osm.live_restaurant_elements(15.31, 76.41, 4000, post)
    assert len(queries) == 2 and [e["id"] for e in els] == [1, 2]


def test_sights_without_a_clear_name_get_a_label_from_kind_or_description():
    assert guide.label_for({"name": "Elephant Stables", "tags": ["culture"], "kind": "attraction",
                            "desc": "Built in the 15th century by the empire to house royal elephants."}) == "Historical"
    assert guide.label_for({"name": "Pampa Sarovar", "tags": ["culture"], "kind": "attraction", "desc": ""}) == "Sight"
    assert guide.label_for({"name": "Old Gate", "tags": ["history"], "kind": "monument"}) == "Historical"
    assert guide.label_for({"name": "Somewhere", "tags": ["x"], "kind": "worship"}) == "Spiritual"


def test_common_heritage_names_are_historical():
    for n in ("Elephant Stables", "Mahanavmi Dibba", "Monolith Bull", "Pushkarani step wells"):
        assert guide.label_for({"name": n, "tags": [], "kind": "attraction"}) == "Historical"


def test_dense_city_query_is_the_light_one():
    light = osm.restaurants_query(48.85, 2.35, 1500)
    assert '["wikidata"]' in light and "opening_hours" not in light and "timeout:60" in light
    assert "opening_hours" in osm.restaurants_query(15.3, 76.4, 3500)
