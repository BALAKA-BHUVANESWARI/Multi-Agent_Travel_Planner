"""Live-price groundwork: the Google Flights link builder and the probe script (no network, no keys)."""
import base64
import json

import pytest

from travel_planner.tools import gflights, live_probe

# Example published in Bright Data's Google Flights docs (SFO <-> London, round trip, 1 adult, economy).
DOC_SAMPLE = ("CBwQAhojEgoyMDI2LTA2LTAxagcIARIDU0ZPcgwIAxIIL20vMDRqcGwaIxIKMjAyNi0wNi0wN2oMCAMSCC9tLzA0anBscgcI"
              "ARIDU0ZPQAFIAXABggELCP___________wGYAQE")


def test_builder_reproduces_the_published_example_exactly():
    assert gflights.build_tfs((gflights.AIRPORT, "SFO"), (gflights.CITY, "/m/04jpl"), "2026-06-01",
                              "2026-06-07") == DOC_SAMPLE


def test_one_way_and_passenger_count_change_the_link():
    a = gflights.build_tfs((1, "DEL"), (1, "GOI"), "2026-12-10", None)
    b = gflights.build_tfs((1, "DEL"), (1, "GOI"), "2026-12-10", "2026-12-14", adults=2)
    assert a != b
    raw = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))
    assert raw.count(b"DEL") == 2 and raw.count(b"GOI") == 2 and raw.count(bytes([0x40, 0x01])) == 2


def test_bad_passenger_counts_are_refused():
    with pytest.raises(ValueError):
        gflights.build_tfs((1, "DEL"), (1, "GOI"), "2026-12-10", None, adults=0)


def test_flights_url_has_currency_and_country():
    u = gflights.flights_url((1, "DEL"), (1, "GOI"), "2026-12-10", "2026-12-14")
    assert u.startswith("https://www.google.com/travel/flights/search?tfs=") and "curr=INR" in u and "gl=in" in u


def _no_keys(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_probe_needs_keys(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    assert live_probe.main() == 2
    out = capsys.readouterr().out
    assert "BRIGHTDATA_API_KEY" in out and "TAVILY_API_KEY" in out
    assert not (tmp_path / "live_probe").exists()


def test_brightdata_alone_saves_answers_and_never_prints_the_key(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "SECRETKEY123")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    seen = []
    monkeypatch.setattr(live_probe, "call", lambda url, key, zone, timeout=90.0: (seen.append(url) or
                                                                              (200, f"ok SECRETKEY123 {len(seen)}")))
    monkeypatch.setattr(live_probe, "tavily_call", lambda *a, **k: pytest.fail("Tavily has no key"))
    assert live_probe.main() == 0
    out = capsys.readouterr().out
    assert "SECRETKEY123" not in out and len(seen) == 4 and "Tavily: skipped" in out
    files = sorted(p.name for p in (tmp_path / "live_probe").iterdir())
    assert files == ["flights_text_json.txt", "flights_tfs_json.txt", "flights_tfs_raw.txt", "hotels_json.txt",
                     "summary.txt"]
    assert all("SECRETKEY123" not in (tmp_path / "live_probe" / f).read_text() for f in files)


TAVILY_SEARCH_ANSWER = json.dumps({
    "answer": "Fares start around \u20b94,500.",
    "results": [{"url": "https://a", "content": "Delhi to Goa from \u20b9 5,200 one way"},
                {"url": "https://b", "content": "no numbers here"},
                {"url": "https://c", "content": "Rs. 6100 return"}]})
TAVILY_EXTRACT_ANSWER = json.dumps({"results": [], "failed_results": [{"url": "https://g", "error": "blocked"}]})


def test_tavily_alone_runs_six_requests_and_summarises(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET999")
    seen = []

    def fake(endpoint, payload, key, timeout=90.0):
        assert key == "tvly-SECRET999"
        seen.append((endpoint, payload))
        body = json.loads(TAVILY_EXTRACT_ANSWER if endpoint == live_probe.TAVILY_EXTRACT else TAVILY_SEARCH_ANSWER)
        body["echo"] = "tvly-SECRET999"                       # a provider that echoes the key must not leak it
        return 200, json.dumps(body)

    monkeypatch.setattr(live_probe, "tavily_call", fake)
    monkeypatch.setattr(live_probe, "call", lambda *a, **k: pytest.fail("Bright Data has no key"))
    assert live_probe.main() == 0
    out = capsys.readouterr().out
    assert "tvly-SECRET999" not in out and "Bright Data: skipped" in out
    assert len(seen) == 6 and [e for e, _ in seen].count(live_probe.TAVILY_EXTRACT) == 2
    assert "3 results, answer with price, 2 mention a price" in out
    assert "0 results, 1 failed, 0 mention a price" in out
    d = tmp_path / "live_probe"
    assert sorted(p.name for p in d.iterdir()) == sorted(
        [f"{n}.txt" for n in live_probe.tavily_requests("2026-12-25", "2026-12-29")] + ["summary.txt"])
    assert all("tvly-SECRET999" not in p.read_text() for p in d.iterdir())
    assert "tavily_flights_search" in (d / "summary.txt").read_text()


def test_both_providers_run_together(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-SECRET")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET")
    monkeypatch.setattr(live_probe, "call", lambda url, key, zone, timeout=90.0: (200, "ok bd-SECRET"))
    monkeypatch.setattr(live_probe, "tavily_call", lambda e, p, key, timeout=90.0: (429, "slow down tvly-SECRET"))
    assert live_probe.main() == 0
    out = capsys.readouterr().out
    assert "skipped" not in out and "bd-SECRET" not in out and "tvly-SECRET" not in out
    assert len(((tmp_path / "live_probe" / "summary.txt").read_text()).splitlines()) == 10


def test_a_network_error_is_reported_and_the_rest_still_run(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET")
    calls = []

    def flaky(endpoint, payload, key, timeout=90.0):
        calls.append(endpoint)
        if len(calls) == 1:
            raise OSError("connection reset by tvly-SECRET")
        return 200, "{}"

    monkeypatch.setattr(live_probe, "tavily_call", flaky)
    assert live_probe.main() == 0
    out = capsys.readouterr().out
    assert len(calls) == 6 and "HTTP 0" in out and "tvly-SECRET" not in out


def test_tavily_requests_ask_for_the_same_trips_as_bright_data():
    reqs = live_probe.tavily_requests("2026-12-25", "2026-12-29")
    assert list(reqs) == ["tavily_flights_search", "tavily_flights_sites", "tavily_hotels_search",
                          "tavily_hotels_sites", "tavily_flights_extract", "tavily_hotels_extract"]
    for name, (endpoint, payload) in reqs.items():
        assert endpoint in (live_probe.TAVILY_SEARCH, live_probe.TAVILY_EXTRACT)
        assert "api_key" not in payload                       # the key goes in the Authorization header only
        if endpoint == live_probe.TAVILY_SEARCH:
            assert payload["query"] and payload["max_results"] == 8
        else:
            assert payload["urls"][0].startswith("https://www.google.com/travel/") and payload["extract_depth"]
    assert "Delhi to Goa" in reqs["tavily_flights_search"][1]["query"]
    assert "Jaipur" in reqs["tavily_hotels_search"][1]["query"]
    assert "makemytrip.com" in reqs["tavily_flights_sites"][1]["include_domains"]
    assert "booking.com" in reqs["tavily_hotels_sites"][1]["include_domains"]


@pytest.mark.parametrize("text,n", [
    ("from \u20b94,500 per night", 1), ("Rs. 12,000 or Rs 9500", 2), ("INR 7,800", 1),
    ("rs\u00e9", 0), ('{"price": "\\u20b98,100"}', 1), ("no price", 0), ("", 0), (None, 0),
])
def test_price_hits(text, n):
    assert live_probe.price_hits(text) == n


def test_describe_tavily_ignores_text_that_is_not_json():
    assert live_probe.describe_tavily("<html>blocked</html>") == ""
    assert live_probe.describe_tavily("[1, 2]") == ""


FLIGHTS_PAGE = (__import__("pathlib").Path(__file__).parent / "fixtures" / "google_flights_del_goi.txt").read_text(
    encoding="utf-8")
FLIGHTS_EXTRACT = json.dumps({"results": [{"url": "https://www.google.com/travel/flights?q=x",
                                             "title": "✈ Trip from New Delhi to Goa", "raw_content": FLIGHTS_PAGE}],
                              "failed_results": []})
HOTELS_EXTRACT = json.dumps({"results": [{
    "url": "https://www.google.com/travel/hotels?q=x", "title": "Search for accommodations in Jaipur",
    "raw_content": "## Hotel A\n[$19 $19 nightly $20 total 1 night with taxes + fees]()\n## Hotel B\n[$67 $67 nightly]()"}],
    "failed_results": []})


def test_flights_page_is_summarised_with_count_and_cheapest_fare():
    out = live_probe.describe_tavily(FLIGHTS_EXTRACT)
    assert "page '✈ Trip from New Delhi to Goa'" in out
    assert "12 flights (2 adults, INR), cheapest economy INR 38980" in out


def test_hotels_page_is_summarised_with_currency_signs():
    out = live_probe.describe_tavily(HOTELS_EXTRACT)
    assert "2 nightly hotel prices" in out and "'$': 5" in out


def test_round2_requests_are_text_queries_for_any_place_and_dated_hotels():
    reqs = live_probe.tavily_round2_requests("2026-12-25", "2026-12-29")
    assert list(reqs) == ["tavily2_flights_text_domestic", "tavily2_flights_text_abroad", "tavily2_hotels_text_dates",
                          "tavily2_hotels_currency_param"]
    urls = {k: p["urls"][0] for k, (e, p) in reqs.items()}
    assert all(e == live_probe.TAVILY_EXTRACT and p["extract_depth"] == "advanced" for e, p in reqs.values())
    assert "Mumbai+to+Paris" in urls["tavily2_flights_text_abroad"] and "2+adults" in urls["tavily2_flights_text_abroad"]
    assert "2026-12-25" in urls["tavily2_hotels_text_dates"] and "curr=INR" in urls["tavily2_hotels_text_dates"]
    assert "currency=INR" in urls["tavily2_hotels_currency_param"]


def test_round2_needs_the_tavily_key(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
    assert live_probe.main(["round2"]) == 2
    assert "TAVILY_API_KEY" in capsys.readouterr().out


def test_round2_skips_bright_data_and_writes_its_own_summary(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-SECRET")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "z")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-SECRET")
    monkeypatch.setattr(live_probe, "call", lambda *a, **k: pytest.fail("round 2 must not call Bright Data"))
    seen = []
    monkeypatch.setattr(live_probe, "tavily_call", lambda e, p, key, timeout=90.0: (seen.append(p) or (200, FLIGHTS_EXTRACT)))
    assert live_probe.main(["round2"]) == 0
    out = capsys.readouterr().out
    assert len(seen) == 4 and "Tavily: 4 requests" in out and "summary_round2.txt" in out and "tvly-SECRET" not in out
    names = sorted(p.name for p in (tmp_path / "live_probe").iterdir())
    assert names == sorted([f"{n}.txt" for n in live_probe.tavily_round2_requests("2026-12-25", "2026-12-29")]
                           + ["summary_round2.txt"])


def test_a_wrong_bright_data_zone_gets_a_plain_hint(monkeypatch, capsys, tmp_path):
    _no_keys(monkeypatch, tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-SECRET")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "brd-customer-x-zone-scraping_browser2")
    monkeypatch.setattr(live_probe, "call", lambda url, key, zone, timeout=90.0: (
        400, 'zone "brd-customer-x-zone-scraping_browser2" not found (it looks like you tried to pass a proxy username)'))
    assert live_probe.main([]) == 0
    assert "not a SERP API zone" in capsys.readouterr().out
