"""Live prices: reading real saved Google pages, the cache and credit cap, fallbacks, and a whole plan.

The pages in tests/fixtures are real (fetched through Tavily Extract on 2026-11-25, links removed):
  google_flights_del_goi.txt     Delhi -> Goa, 25 Dec 2026, 2 adults, round trip, in rupees
  google_flights_bom_cdg.txt     Mumbai -> Paris, same dates, found by typing the city names
  google_hotels_jaipur_usd.txt   Jaipur hotels for 25-29 Dec, shown in US dollars
No test touches the network: the page reader and the exchange-rate call are replaced by fakes.
"""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from travel_planner import config
from travel_planner.tools import impl, live

FIX = Path(__file__).parent / "fixtures"
DEL_GOI = (FIX / "google_flights_del_goi.txt").read_text(encoding="utf-8")
BOM_CDG = (FIX / "google_flights_bom_cdg.txt").read_text(encoding="utf-8")
JAIPUR = (FIX / "google_hotels_jaipur_usd.txt").read_text(encoding="utf-8")
DEP, RET = date(2026, 12, 25), date(2026, 12, 29)
SHELL = "Loading results\n## Search results\nLanguage English (United States) Location India Currency INR"


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    monkeypatch.setenv("LIVE_DAILY_CREDITS", "30")


@pytest.fixture
def pages(monkeypatch, key):
    """Replace the network page read: pages['text'] is served and every read is counted in pages['reads']."""
    box = {"text": DEL_GOI, "reads": []}

    def fake(url):
        box["reads"].append(url)
        return box["text"] if not isinstance(box["text"], list) else box["text"].pop(0)
    monkeypatch.setattr(live, "_read_page", fake)
    return box


@pytest.fixture
def served(monkeypatch):
    """Skip the cache and cap entirely: get_page just returns this text."""
    box = {"text": DEL_GOI}
    monkeypatch.setattr(live, "get_page", lambda url, ok, attempts=2: (box["text"], "2026-11-25T10:45:00+00:00", False))
    return box


@pytest.fixture
def fx(monkeypatch):
    monkeypatch.setattr(live, "rate_to_inr", lambda code: (88.0, "2026-11-25") if code != "INR" else (1.0, ""))


# --------------------------------------------------------------------- search links
def test_known_places_use_airport_codes_and_unknown_places_use_names():
    known = live.flights_url("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)
    assert known.startswith("https://www.google.com/travel/flights/search?tfs=") and "curr=INR" in known
    named = live.flights_url("mumbai", "paris", "Mumbai", "Paris", DEP, RET, 2)
    assert named.startswith("https://www.google.com/travel/flights?q=Flights+from+Mumbai+to+Paris+on+2026-12-25")
    assert "for+2+adults" in named and "curr=INR" in named
    assert "for+1+adult&" in live.flights_url("mumbai", "paris", "Mumbai", "Paris", DEP, RET, 1)


def test_hotel_link_carries_the_dates():
    u = live.hotels_url("Jaipur", DEP, RET)
    assert "hotels+in+Jaipur+from+2026-12-25+to+2026-12-29+for+2+adults" in u


# ------------------------------------------------------------------ page read + cache
def test_page_is_read_once_then_served_from_cache(pages):
    ok = lambda t: "Search results" in t or "Prices include" in t        # noqa: E731
    first = live.get_page("https://x/1", ok)
    second = live.get_page("https://x/1", ok)
    assert first[0] == second[0] and first[2] is False and second[2] is True and len(pages["reads"]) == 1
    assert live.credits_used_today() == live.CREDITS_PER_PAGE


def test_an_empty_shell_is_retried_once_and_never_cached(pages):
    pages["text"] = [SHELL, DEL_GOI]
    ok = lambda t: "Prices include" in t                                   # noqa: E731
    text, _, cached = live.get_page("https://x/2", ok)
    assert "Prices include" in text and not cached and len(pages["reads"]) == 2
    assert live.credits_used_today() == 2 * live.CREDITS_PER_PAGE
    pages["text"] = SHELL
    with pytest.raises(live.LiveUnavailable, match="without any results"):
        live.get_page("https://x/3", ok)
    assert len(pages["reads"]) == 4                                        # two more reads, nothing cached
    with pytest.raises(live.LiveUnavailable):
        live.get_page("https://x/3", ok)


def test_the_daily_credit_cap_stops_further_reads(pages, monkeypatch):
    monkeypatch.setenv("LIVE_DAILY_CREDITS", "4")
    ok = lambda t: True                                                    # noqa: E731
    live.get_page("https://x/a", ok)
    live.get_page("https://x/b", ok)
    with pytest.raises(live.LiveUnavailable, match="limit"):
        live.get_page("https://x/c", ok)
    assert len(pages["reads"]) == 2
    live.get_page("https://x/a", ok)                                       # still free: it is cached


def test_a_zero_hour_cache_always_reads(pages, monkeypatch):
    monkeypatch.setenv("LIVE_CACHE_HOURS", "0")
    live.get_page("https://x/z", lambda t: True)
    live.get_page("https://x/z", lambda t: True)
    assert len(pages["reads"]) == 2


@pytest.mark.parametrize("status,words", [(401, "rejected the key"), (403, "rejected the key"),
                                          (429, "rate limiting"), (432, "rate limiting"),
                                          (500, "HTTP 500")])
def test_provider_errors_become_plain_reasons(monkeypatch, key, status, words):
    monkeypatch.setattr(live, "_post", lambda url, body, k, timeout=90.0: (status, "{}"))
    with pytest.raises(live.LiveUnavailable, match=words):
        live._read_page("https://x")


def test_network_error_text_never_contains_the_key(monkeypatch, key):
    def boom(url, body, k, timeout=90.0):
        raise OSError(f"reset while sending {k}")
    monkeypatch.setattr(live, "_post", boom)
    with pytest.raises(live.LiveUnavailable) as e:
        live._read_page("https://x")
    assert "tvly-TESTKEY" not in str(e.value) and "OSError" in str(e.value)


def test_page_text_is_taken_from_the_provider_answer_and_tidied(monkeypatch, key):
    body = {"results": [{"raw_content": "[Sign in](https://accounts.google.com/x) ![Image 1](https://img/1.png)ok"}]}
    sent = {}

    def fake(url, payload, k, timeout=90.0):
        sent.update(url=url, payload=payload, key=k)
        return 200, json.dumps(body)
    monkeypatch.setattr(live, "_post", fake)
    assert live._read_page("https://www.google.com/travel/flights?q=x") == "[Sign in]() ok"
    assert sent["url"] == live.TAVILY_EXTRACT and sent["key"] == "tvly-TESTKEY"
    assert sent["payload"] == {"urls": ["https://www.google.com/travel/flights?q=x"], "extract_depth": "advanced",
                               "timeout": 60}


def test_no_results_in_the_answer_gives_an_empty_page(monkeypatch, key):
    monkeypatch.setattr(live, "_post", lambda *a, **k: (200, json.dumps({"results": [], "failed_results": [{}]})))
    assert live._read_page("https://x") == ""
    monkeypatch.setattr(live, "_post", lambda *a, **k: (200, "<html>not json</html>"))
    assert live._read_page("https://x") == ""


def test_without_a_key_nothing_is_read(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(live.LiveUnavailable, match="no Tavily key"):
        live._read_page("https://x")


# ------------------------------------------------------------------------ exchange rate
def test_exchange_rate_formats_and_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "_get_json", lambda url, timeout=10.0: (calls.append(url) or {"rate": 88.25,
                                                                                             "date": "2026-11-25"}))
    assert live.rate_to_inr("usd") == (88.25, "2026-11-25") and live.rate_to_inr("USD")[0] == 88.25
    assert len(calls) == 1 and calls[0].endswith("/rate/USD/INR")
    monkeypatch.setattr(live, "_get_json", lambda url, timeout=10.0: {"base": "EUR", "rates": {"INR": 96.5}})
    assert live.rate_to_inr("EUR") == (96.5, "")
    assert live.rate_to_inr("INR") == (1.0, "")


@pytest.mark.parametrize("answer", [OSError("offline"), {"oops": 1}, {"rate": 0}, {"rate": "x"}])
def test_exchange_rate_failures_are_reported(monkeypatch, answer):
    def fake(url, timeout=10.0):
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(live, "_get_json", fake)
    with pytest.raises(live.LiveUnavailable, match="exchange rate"):
        live.rate_to_inr("GBP")


# ------------------------------------------------------------------------- flights
def test_delhi_goa_gives_best_cheaper_and_cheapest_real_flights(served):
    r = live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)
    assert r["estimated"] is False and r["live"] is True and r["source"] == live.SOURCE_FLIGHTS
    assert r["fetched_at"] == "2026-11-25T10:45:00+00:00" and r["route"] == "DEL→GOI"
    best, cheaper, cheapest = r["options"]
    assert [o["id"] for o in r["options"]] == ["best", "early_late", "one_stop"]
    assert (best["airline"], best["depart_out"], best["arrive_out"], best["page_total"]) == ("IndiGo", "17:10",
                                                                                              "19:45", 40702)
    assert best["price_pp"] == 20351 and best["stops"] == 0 and best["duration_h"] == 2.6
    assert cheapest["page_total"] == 38980 and cheapest["stops"] == 1 and "AMD" in cheapest["label"]
    assert best["price_pp"] >= cheaper["price_pp"] >= cheapest["price_pp"]
    assert all(o["estimated"] is False and o["mode"] == "flight" for o in r["options"])


def test_return_time_is_assumed_and_says_so(served):
    best = live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)["options"][0]
    assert best["depart_back"] == "17:00" and best["arrive_back"] == "19:35"          # 17:00 + 2 h 35
    assert "not shown by Google" in best["note"]


def test_page_total_is_split_between_the_travellers(served):
    r = live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)
    assert all(o["price_pp"] * 2 in (o["page_total"], o["page_total"] - 1, o["page_total"] + 1) for o in r["options"])
    assert "divided by 2" in r["price_basis"] and "taxes and fees included" in r["price_basis"]


def test_a_city_found_by_name_works_and_next_day_arrivals_are_left_out(served):
    served["text"] = BOM_CDG
    r = live.flights("mumbai", "paris", "Mumbai", "Paris", DEP, RET, 2)
    assert r["route"] == "BOM→CDG"
    best, cheaper, cheapest = r["options"]
    assert (best["airline"], best["page_total"]) == ("Etihad", 137260)             # Google's first same-day fare
    assert cheapest["airline"] == "Lufthansa" and cheapest["page_total"] == 130936 and cheaper["page_total"] == 130936
    assert all(o["arrive_out"] >= "00:00" for o in r["options"])
    assert 178718 not in [o["page_total"] for o in r["options"]]              # the Gulf Air row lands on the 26th


def test_wrong_number_of_adults_is_refused(served):
    served["text"] = DEL_GOI.replace("for 2 adults", "for 3 adults")
    with pytest.raises(live.LiveUnavailable, match="3 adults, not 2"):
        live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)


def test_page_that_does_not_say_how_many_adults_is_refused(served):
    served["text"] = DEL_GOI.replace("Prices include required taxes + fees for 2 adults.", "Prices include fees.")
    with pytest.raises(live.LiveUnavailable, match="unknown number"):
        live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)


def test_prices_in_another_currency_are_refused(served):
    served["text"] = DEL_GOI.replace("Currency INR", "Currency USD")
    with pytest.raises(live.LiveUnavailable, match="USD, not rupees"):
        live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)


def test_fares_for_other_dates_are_refused(served):
    with pytest.raises(live.LiveUnavailable, match="same-day economy fares"):
        live.flights("delhi", "goa", "Delhi", "Goa", date(2026, 12, 26), date(2026, 12, 30), 2)


def test_a_different_route_than_asked_is_refused(served):
    with pytest.raises(live.LiveUnavailable, match="different route"):
        live.flights("delhi", "jaipur", "Delhi", "Jaipur", DEP, RET, 2)


@pytest.mark.parametrize("n", [0, 10, 12])
def test_google_cannot_price_more_than_nine(served, n):
    with pytest.raises(live.LiveUnavailable, match="1 to 9"):
        live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, n)


def test_when_googles_pick_is_the_cheapest_all_three_options_agree(served):
    only = [l for l in DEL_GOI.splitlines() if "₹38,980" in l or not l.lstrip().startswith("*")]
    served["text"] = "\n".join(only)
    opts = live.flights("delhi", "goa", "Delhi", "Goa", DEP, RET, 2)["options"]
    assert len({o["page_total"] for o in opts}) == 1 and opts[0]["page_total"] == 38980


# -------------------------------------------------------------------------- hotels
def test_jaipur_hotels_are_converted_and_tiered(served, fx):
    served["text"] = JAIPUR
    r = live.hotels("Jaipur", DEP, 4)
    assert r["estimated"] is False and r["source"] == live.SOURCE_HOTELS and r["hotels_listed"] == 10
    by_id = {o["id"]: o for o in r["options"]}
    assert by_id["budget"]["name"] == "Hotel Narayan villas" and by_id["budget"]["price_night_per_room"] == 1254
    assert by_id["2star"]["name"] == "HOTEL RUDRA SHIVALIKA" and by_id["2star"]["price_night_per_room"] == 1364
    assert by_id["3star"]["name"] == "Hotel Kalyan" and by_id["3star"]["price_night_per_room"] == 3630
    assert "3-star" in by_id["3star"]["label"] and "rated 4.2" in by_id["3star"]["label"]
    assert by_id["3star"]["price_night_per_room"] >= by_id["2star"]["price_night_per_room"] \
        >= by_id["budget"]["price_night_per_room"]


def test_hotel_price_is_the_stay_total_with_taxes_divided_by_nights(served, fx):
    served["text"] = JAIPUR
    kalyan = next(o for o in live.hotels("Jaipur", DEP, 4)["options"] if o["name"] == "Hotel Kalyan")
    assert kalyan["price_night_per_room"] == round(165 / 4 * 88)                   # $165 for 4 nights, not $39 x 88


def test_dollar_prices_come_with_a_conversion_note(served, fx):
    served["text"] = JAIPUR
    r = live.hotels("Jaipur", DEP, 4)
    assert "USD" in r["fx_note"] and "88 INR per USD" in r["fx_note"] and "2026-11-25" in r["fx_note"]
    assert "taxes and fees included" in r["price_basis"]


def test_rupee_prices_need_no_conversion(served, monkeypatch):
    served["text"] = JAIPUR.replace("$", "₹")
    monkeypatch.setattr(live, "rate_to_inr", lambda code: pytest.fail("no conversion needed"))
    r = live.hotels("Jaipur", DEP, 4)
    assert r["fx_note"] == "" and {o["id"]: o["price_night_per_room"] for o in r["options"]}["3star"] == 41   # 165/4


def test_prices_for_other_dates_are_refused(served, fx):
    served["text"] = JAIPUR
    with pytest.raises(live.LiveUnavailable, match="other dates"):
        live.hotels("Jaipur", date(2026, 12, 26), 4)


def test_a_stay_that_runs_into_the_next_month_is_matched_too(served, fx):
    served["text"] = JAIPUR.replace("Dec 25 – 29", "Dec 30 – Jan 3")
    assert live.hotels("Jaipur", date(2026, 12, 30), 4)["options"]


def test_mixed_currencies_are_refused(served, fx):
    served["text"] = JAIPUR.replace("$126 $126 nightly $599", "€126 €126 nightly €599")
    with pytest.raises(live.LiveUnavailable, match="mixed currencies"):
        live.hotels("Jaipur", DEP, 4)


def test_cards_priced_for_another_number_of_nights_are_dropped(served, fx):
    served["text"] = JAIPUR.replace("total 4 nights", "total 2 nights")
    with pytest.raises(live.LiveUnavailable, match="too short"):
        live.hotels("Jaipur", DEP, 4)


def test_too_few_hotels_means_the_page_is_not_accepted(pages, fx):
    pages["text"] = JAIPUR.split("## Hotel Kalyan")[0].replace("## Radisson", "text Radisson")      # only 2 hotels left
    with pytest.raises(live.LiveUnavailable, match="without any results"):
        live.hotels("Jaipur", DEP, 4)
    assert len(pages["reads"]) == 2                                         # read twice, then gave up


def test_unrated_hotels_still_count(served, fx):
    served["text"] = re.sub(r"\[\d\.\d \([\d.,K]+\) 5 4 3 2 1", "[", JAIPUR)
    assert live.hotels("Jaipur", DEP, 4)["options"]


# --------------------------------------------------- through the tool functions
@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(config, "live_prices_enabled", lambda: True)


def test_search_flights_returns_live_fares_when_they_work(on, served, fx):
    r = impl.search_flights("delhi", "goa", "2026-12-25", "2026-12-29", 2)
    assert r["estimated"] is False and r["source"] == live.SOURCE_FLIGHTS and r["mode"] == "flight"
    assert r["currency"] == "INR" and r["distance_km"] > 1000 and "live_note" not in r
    assert [o["id"] for o in r["options"]] == ["best", "early_late", "one_stop"]


def test_search_flights_falls_back_to_the_estimate_and_says_why(on, monkeypatch):
    def down(*a, **k):
        raise live.LiveUnavailable("Tavily is rate limiting or the plan's credits are used up")
    monkeypatch.setattr(live, "get_page", down)
    r = impl.search_flights("delhi", "goa", "2026-12-25", "2026-12-29", 2)
    assert r["estimated"] is True and r["source"] == "synthetic-estimator"
    assert "Live fares were unavailable (Tavily is rate limiting" in r["live_note"]
    assert [o["id"] for o in r["options"]] == ["best", "early_late", "one_stop"]


def test_an_unexpected_error_inside_the_live_code_cannot_break_the_search(on, monkeypatch):
    monkeypatch.setattr(live, "get_page", lambda *a, **k: 1 / 0)
    r = impl.search_flights("delhi", "goa", "2026-12-25", "2026-12-29", 2)
    assert r["estimated"] is True and "ZeroDivisionError" in r["live_note"]


def test_live_is_skipped_for_other_modes_short_hops_and_when_asked_not_to(on, monkeypatch):
    monkeypatch.setattr(live, "get_page", lambda *a, **k: pytest.fail("must not spend credits here"))
    for mode in ("train", "bus", "car", "bike"):
        assert impl.search_flights("delhi", "jaipur", "2026-12-25", "2026-12-29", 2, mode=mode)["estimated"] is True
    short = impl.search_flights("delhi", "jaipur", "2026-12-25", "2026-12-29", 2)             # about 240 km: not flown
    assert short["estimated"] is True and short["mode"] == "ground"
    asked = impl.search_flights("delhi", "goa", "2026-12-25", "2026-12-29", 2, live_prices=False)
    assert asked["estimated"] is True and "live_note" not in asked


def test_live_is_off_without_a_key_or_in_offline_mode(monkeypatch):
    monkeypatch.setattr(live, "get_page", lambda *a, **k: pytest.fail("must not be called"))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert impl.search_flights("delhi", "goa", "2026-12-25", "2026-12-29", 2)["estimated"] is True
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    monkeypatch.setenv("REAL_DATA", "0")
    assert not config.live_prices_enabled()
    monkeypatch.setenv("REAL_DATA", "1")
    monkeypatch.setenv("LIVE_PRICES", "0")
    assert not config.live_prices_enabled()
    monkeypatch.setenv("LIVE_PRICES", "1")
    assert config.live_prices_enabled()


def test_search_hotels_live_and_fallback(on, served, fx, monkeypatch):
    served["text"] = JAIPUR
    r = impl.search_hotels("jaipur", "2026-12-25", 4, 2)
    assert r["estimated"] is False and r["rooms"] == 1 and r["source"] == live.SOURCE_HOTELS
    assert {o["id"] for o in r["options"]} == {"3star", "2star", "budget"}
    monkeypatch.setattr(live, "get_page", lambda *a, **k: (_ for _ in ()).throw(live.LiveUnavailable("x")))
    r = impl.search_hotels("jaipur", "2026-12-25", 4, 2)
    assert r["estimated"] is True and "Live hotel prices were unavailable (x)" in r["live_note"]


def test_rooms_follow_the_traveller_count_for_live_hotels(on, served, fx):
    served["text"] = JAIPUR
    assert impl.search_hotels("jaipur", "2026-12-25", 4, 5)["rooms"] == 3


# --------------------------------------------------------------- a whole plan, live
def live_pages():
    """Serve the saved flights page for flight links and the saved hotels page for hotel links; count the reads."""
    reads = []

    def fake(url):
        reads.append(url)
        return JAIPUR if "/travel/hotels" in url else DEL_GOI
    return fake, reads


def plan_text(budget):
    return f"Plan a 5 day trip to goa from delhi starting 25 December, budget {budget} for 2"


def test_whole_plan_uses_live_prices_and_labels_them(make, on, key, fx, monkeypatch):
    fake, reads = live_pages()
    monkeypatch.setattr(live, "_read_page", fake)
    s = make().start(plan_text("3 lakh"))
    assert s["status"] == "awaiting_approval"
    fl, ho = s["flight"], s["hotel"]
    assert fl["live"] is True and fl["estimated"] is False and fl["source"] == live.SOURCE_FLIGHTS
    assert fl["selected"]["price_pp"] == 20351 and fl["selected"]["total"] == 40702
    assert ho["live"] is True and ho["selected"]["total"] == ho["selected"]["price_night_per_room"] * 4 * 1
    assert s["budget_report"]["live"] == ["flight", "hotel"] and s["budget_report"]["lines"]["flight"] == 40702
    assert not [i for i in s["critic_issues"] if i["severity"] == "blocking"]
    text = s["summary"] if "summary" in s else ""
    assert "live: Google Flights via Tavily" in text and "live: Google Hotels via Tavily" in text
    assert "converted at 88 INR per USD" in text and "Return flight time is not shown" in text
    assert "live listings" in text and "synthetic ESTIMATES, not live" not in text
    assert any("picked" in l["msg"] and "live: Google Flights" in l["msg"] for l in s["log"] if l["agent"] == "flight")


def test_a_tight_budget_picks_cheaper_live_options_without_new_page_reads(make, on, key, fx, monkeypatch):
    fake, reads = live_pages()
    monkeypatch.setattr(live, "_read_page", lambda url: fake(url))
    normal = make().start(plan_text("5 lakh"))
    assert len(reads) == 2                                                         # one flights page, one hotels page
    total = normal["budget_report"]["total"]
    tight = make().start(plan_text(str(int(total * 0.93))))
    assert tight["retries"] >= 1 and tight["strategy"] in ("cheaper", "cheapest")
    assert tight["flight"]["selected"]["page_total"] <= normal["flight"]["selected"]["page_total"]
    assert tight["budget_report"]["total"] < total
    assert len(reads) == 2                                                         # replans re-used the cached pages
    assert not [i for i in tight["critic_issues"] if i["severity"] == "blocking"]


def test_whole_plan_still_works_when_live_prices_fail(make, on, key, monkeypatch):
    monkeypatch.setattr(live, "_read_page", lambda url: (_ for _ in ()).throw(live.LiveUnavailable("Tavily down")))
    s = make().start(plan_text("3 lakh"))
    assert s["status"] == "awaiting_approval" and s["flight"]["estimated"] is True and not s["flight"]["live"]
    assert s["budget_report"]["live"] == []
    warns = " ".join(s["warnings"])
    assert "Live fares were unavailable (Tavily down)" in warns and "Live hotel prices were unavailable" in warns
    assert "synthetic ESTIMATES, not live fares" in s.get("summary", "")


def test_the_travel_choice_cards_do_not_spend_credits(make, on, key, monkeypatch):
    monkeypatch.setattr(live, "_read_page", lambda url: pytest.fail("the choice cards must not read live pages"))
    p = make()
    p.deps.ask_travel_mode = True
    s = p.start("Plan a 5 day trip to goa from delhi starting 25 December, budget 3 lakh for 2")
    assert s["status"] == "needs_info" and s["travel_options"]
