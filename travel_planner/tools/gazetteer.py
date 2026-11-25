"""Offline gazetteer of popular destinations (India + worldwide).

Why it exists: place lookup normally uses the free Open-Meteo geocoding API, but this
list makes the most common places work offline, resolves ambiguous names the way travellers
mean them ("Paris" is the French one) and keeps tests/evals deterministic.

Line format:  Name | country code | lat | lon | population (thousands) | aliases (comma separated) | flags
Flag ``x`` = do not scan free text for this name (it is also an everyday word, e.g. "Nice").
Coordinates are approximate (city centre); they only drive distance, weather and map lookups.
"""
from __future__ import annotations

import re
import unicodedata

_RAW = """
Shimla|IN|31.10|77.17|170|simla
Rishikesh|IN|30.09|78.27|100|
Haridwar|IN|29.95|78.16|230|hardwar
Varanasi|IN|25.32|82.99|1200|banaras,benares,kashi
Agra|IN|27.18|78.01|1600|
Amritsar|IN|31.63|74.87|1100|
Darjeeling|IN|27.04|88.26|120|
Gangtok|IN|27.34|88.61|100|sikkim
Munnar|IN|10.09|77.06|40|
Alleppey|IN|9.49|76.34|175|alappuzha,alleppy
Mysuru|IN|12.30|76.65|920|mysore
Hampi|IN|15.34|76.46|3|
Pondicherry|IN|11.93|79.83|240|puducherry
Ooty|IN|11.41|76.70|90|udhagamandalam
Kodaikanal|IN|10.24|77.49|36|
Leh|IN|34.16|77.58|30|ladakh,leh ladakh
Srinagar|IN|34.08|74.80|1200|kashmir
Mussoorie|IN|30.46|78.07|30|mussorie
Nainital|IN|29.39|79.46|41|
Jaisalmer|IN|26.92|70.91|65|
Jodhpur|IN|26.24|73.02|1100|
Pushkar|IN|26.49|74.55|22|
Mount Abu|IN|24.59|72.71|22|
Khajuraho|IN|24.85|79.92|20|
Shillong|IN|25.57|91.88|143|meghalaya
Guwahati|IN|26.14|91.74|1000|
Port Blair|IN|11.62|92.73|100|andaman,andamans,andaman islands
Gokarna|IN|14.55|74.32|27|
Coorg|IN|12.42|75.74|33|madikeri,kodagu
Chandigarh|IN|30.73|76.78|1100|
Dehradun|IN|30.32|78.03|580|
Kanyakumari|IN|8.09|77.54|20|
Madurai|IN|9.93|78.12|1500|
Rameswaram|IN|9.29|79.31|45|
Mahabalipuram|IN|12.62|80.19|15|mamallapuram
Bhubaneswar|IN|20.30|85.82|840|
Puri|IN|19.81|85.83|200|
Nashik|IN|20.00|73.79|1500|nasik
Aurangabad|IN|19.88|75.34|1200|
Lonavala|IN|18.75|73.41|58|lonavla
Mahabaleshwar|IN|17.92|73.66|13|
Diu|IN|20.71|70.99|24|
Bhuj|IN|23.25|69.67|150|kutch,rann of kutch
Indore|IN|22.72|75.86|2000|
Bhopal|IN|23.26|77.41|1800|
Ayodhya|IN|26.80|82.20|80|
Patna|IN|25.59|85.14|1700|
Ranchi|IN|23.34|85.31|1100|
Visakhapatnam|IN|17.69|83.22|2000|vizag,vishakhapatnam
Tirupati|IN|13.63|79.42|300|
Thiruvananthapuram|IN|8.52|76.94|960|trivandrum
Kovalam|IN|8.40|76.98|15|
Varkala|IN|8.73|76.72|40|
Wayanad|IN|11.61|76.08|30|kalpetta
Kozhikode|IN|11.26|75.78|600|calicut
Mangaluru|IN|12.91|74.86|500|mangalore
Dharamshala|IN|32.22|76.32|53|mcleod ganj,mcleodganj,dharamsala
Kasol|IN|32.01|77.31|1|
Spiti Valley|IN|32.23|78.07|2|spiti,kaza
Sawai Madhopur|IN|26.01|76.35|120|ranthambore
Bikaner|IN|28.02|73.31|650|
Ajmer|IN|26.45|74.64|550|
Gwalior|IN|26.22|78.18|1100|
Orchha|IN|25.35|78.64|10|
Kolhapur|IN|16.70|74.24|550|
Surat|IN|21.17|72.83|5000|
Vadodara|IN|22.31|73.18|1800|baroda
Coimbatore|IN|11.02|76.96|1100|
Jammu|IN|32.73|74.86|500|
Tawang|IN|27.59|91.86|11|
Dubai|AE|25.20|55.27|3300|
Abu Dhabi|AE|24.45|54.38|1500|
Singapore|SG|1.35|103.82|5600|
Bangkok|TH|13.76|100.50|10500|
Phuket|TH|7.88|98.39|80|
Pattaya|TH|12.93|100.88|120|
Chiang Mai|TH|18.79|98.98|130|
Krabi|TH|8.09|98.91|30|
Bali|ID|-8.65|115.22|700|denpasar,kuta,seminyak
Ubud|ID|-8.51|115.26|30|
Kuala Lumpur|MY|3.14|101.69|1800|kl
Langkawi|MY|6.35|99.80|65|
Penang|MY|5.41|100.33|700|george town
Hanoi|VN|21.03|105.85|8000|
Ho Chi Minh City|VN|10.82|106.63|9000|saigon,hcmc
Da Nang|VN|16.05|108.21|1200|danang
Hoi An|VN|15.88|108.34|120|
Colombo|LK|6.93|79.86|750|
Kandy|LK|7.29|80.63|125|
Kathmandu|NP|27.72|85.32|1400|
Pokhara|NP|28.21|83.99|520|
Thimphu|BT|27.47|89.64|115|bhutan
Paro|BT|27.43|89.41|15|
Dhaka|BD|23.81|90.41|10000|
Maldives|MV|4.18|73.51|130|male atoll
Tokyo|JP|35.68|139.69|14000|
Kyoto|JP|35.01|135.77|1450|
Osaka|JP|34.69|135.50|2700|
Seoul|KR|37.57|126.98|9700|
Hong Kong|HK|22.32|114.17|7500|hongkong
Macau|MO|22.20|113.54|650|
Beijing|CN|39.90|116.40|21000|
Shanghai|CN|31.23|121.47|24000|
Taipei|TW|25.03|121.57|2600|
Siem Reap|KH|13.36|103.86|245|angkor wat,angkor
Phnom Penh|KH|11.56|104.93|2000|
Manila|PH|14.60|120.98|1800|
Cebu|PH|10.32|123.89|960|
Luang Prabang|LA|19.89|102.13|56|
Yangon|MM|16.87|96.20|5200|rangoon
London|GB|51.51|-0.13|8900|
Edinburgh|GB|55.95|-3.19|540|
Paris|FR|48.86|2.35|2100|
Nice|FR|43.70|7.27|340||x
Rome|IT|41.90|12.50|2800|roma
Venice|IT|45.44|12.32|255|venezia
Florence|IT|43.77|11.26|380|firenze
Milan|IT|45.46|9.19|1400|milano
Barcelona|ES|41.39|2.17|1600|
Madrid|ES|40.42|-3.70|3300|
Seville|ES|37.39|-5.98|690|sevilla
Lisbon|PT|38.72|-9.14|545|lisboa
Porto|PT|41.15|-8.61|230|oporto
Amsterdam|NL|52.37|4.90|870|
Brussels|BE|50.85|4.35|1200|
Berlin|DE|52.52|13.40|3700|
Munich|DE|48.14|11.58|1500|munchen
Prague|CZ|50.08|14.44|1300|praha
Vienna|AT|48.21|16.37|1900|wien
Budapest|HU|47.50|19.04|1750|
Zurich|CH|47.38|8.54|420|
Interlaken|CH|46.69|7.86|6|
Geneva|CH|46.20|6.14|200|
Lucerne|CH|47.05|8.31|82|luzern
Athens|GR|37.98|23.73|640|
Santorini|GR|36.39|25.46|15|thira
Istanbul|TR|41.01|28.98|15500|
Dubrovnik|HR|42.65|18.09|42|
Copenhagen|DK|55.68|12.57|650|
Stockholm|SE|59.33|18.07|980|
Oslo|NO|59.91|10.75|700|
Reykjavik|IS|64.15|-21.94|135|iceland
Dublin|IE|53.35|-6.26|590|
Krakow|PL|50.06|19.94|780|cracow
Doha|QA|25.29|51.53|1100|
Muscat|OM|23.59|58.41|1400|
Cairo|EG|30.04|31.24|10000|
Marrakech|MA|31.63|-8.01|930|marrakesh
Cape Town|ZA|-33.92|18.42|4600|
Nairobi|KE|-1.29|36.82|4400|
Zanzibar|TZ|-6.17|39.20|220|
Amman|JO|31.95|35.93|4000|
Mauritius|MU|-20.16|57.50|150|port louis
New York|US|40.71|-74.01|8400|nyc,new york city,manhattan
Los Angeles|US|34.05|-118.24|3900|la
San Francisco|US|37.77|-122.42|870|sf
Las Vegas|US|36.17|-115.14|650|vegas
Miami|US|25.76|-80.19|450|
Chicago|US|41.88|-87.63|2700|
Orlando|US|28.54|-81.38|310|
Washington|US|38.91|-77.04|690|washington dc,washington d.c.
Boston|US|42.36|-71.06|690|
Seattle|US|47.61|-122.33|750|
Honolulu|US|21.31|-157.86|350|hawaii
Toronto|CA|43.65|-79.38|2900|
Vancouver|CA|49.28|-123.12|680|
Mexico City|MX|19.43|-99.13|9200|
Cancun|MX|21.16|-86.85|900|
Rio de Janeiro|BR|-22.91|-43.17|6700|rio
Buenos Aires|AR|-34.60|-58.38|3000|
Lima|PE|-12.05|-77.04|9700|
Cusco|PE|-13.53|-71.97|430|cuzco,machu picchu
Sydney|AU|-33.87|151.21|5300|
Melbourne|AU|-37.81|144.96|5000|
Gold Coast|AU|-28.02|153.40|600|
Auckland|NZ|-36.85|174.76|1650|
Queenstown|NZ|-45.03|168.66|16|
"""

COUNTRY_NAMES = {
    "IN": "India", "AE": "United Arab Emirates", "SG": "Singapore", "TH": "Thailand", "ID": "Indonesia",
    "MY": "Malaysia", "VN": "Vietnam", "LK": "Sri Lanka", "NP": "Nepal", "BT": "Bhutan", "BD": "Bangladesh",
    "MV": "Maldives", "JP": "Japan", "KR": "South Korea", "HK": "Hong Kong", "MO": "Macau", "CN": "China",
    "TW": "Taiwan", "KH": "Cambodia", "PH": "Philippines", "LA": "Laos", "MM": "Myanmar",
    "GB": "United Kingdom", "FR": "France", "IT": "Italy", "ES": "Spain", "PT": "Portugal", "NL": "Netherlands",
    "BE": "Belgium", "DE": "Germany", "CZ": "Czechia", "AT": "Austria", "HU": "Hungary", "CH": "Switzerland",
    "GR": "Greece", "TR": "Turkey", "HR": "Croatia", "DK": "Denmark", "SE": "Sweden", "NO": "Norway",
    "IS": "Iceland", "IE": "Ireland", "PL": "Poland", "QA": "Qatar", "OM": "Oman", "EG": "Egypt",
    "MA": "Morocco", "ZA": "South Africa", "KE": "Kenya", "TZ": "Tanzania", "JO": "Jordan", "MU": "Mauritius",
    "US": "United States", "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "AR": "Argentina", "PE": "Peru",
    "AU": "Australia", "NZ": "New Zealand",
}


def normalize(text: str) -> str:
    """Lower-case, accent-free, punctuation-free key: 'Zürich ' -> 'zurich'."""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _load() -> tuple[dict, dict]:
    by_key: dict[str, dict] = {}
    by_alias: dict[str, dict] = {}
    for line in _RAW.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (7 - len(parts))
        name, cc, lat, lon, pop, aliases, flags = parts[:7]
        key = normalize(name)
        entry = {"slug": key.replace(" ", "-"), "name": name, "cc": cc, "country": COUNTRY_NAMES.get(cc, cc),
                 "lat": float(lat), "lon": float(lon), "population": int(pop) * 1000,
                 "scan": "x" not in flags, "aliases": [normalize(a) for a in aliases.split(",") if a.strip()]}
        by_key[key] = entry
        by_alias[key] = entry
        for a in entry["aliases"]:
            by_alias.setdefault(a, entry)
    return by_key, by_alias


PLACES, _BY_ALIAS = _load()


def lookup(query: str) -> dict | None:
    """Exact (accent/case-insensitive) match on a place name, alias or slug."""
    key = normalize(query)
    return _BY_ALIAS.get(key) or _BY_ALIAS.get(key.replace("-", " "))


def scan_names() -> list[tuple[str, dict]]:
    """(phrase, entry) pairs to look for in free text, longest first."""
    pairs = [(a, e) for a, e in _BY_ALIAS.items() if e["scan"] or a != normalize(e["name"])]
    # a flagged-risky *name* is skipped, but its explicit aliases (e.g. 'maldives') still scan
    return sorted(pairs, key=lambda p: -len(p[0]))
