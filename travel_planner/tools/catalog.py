"""Curated offline data for the 5 supported destinations.

All prices are rough, hand-entered ESTIMATES (INR, per person, Indian-resident
entry fees) and are labelled as such everywhere in the product. They exist so
the planner works with no network and no API keys.

Place fields: id, name, tags, outdoor, cost (INR pp), hours, slot
(morning|afternoon|evening|any), desc. List order = rough popularity.
"""
from __future__ import annotations


def _p(id, name, tags, outdoor, cost, hours, slot, desc):
    return {"id": id, "name": name, "tags": tags, "outdoor": outdoor, "cost": cost,
            "hours": hours, "slot": slot, "desc": desc}


DESTINATIONS = {
    "goa": {
        "name": "Goa", "lat": 15.38, "lon": 73.83, "cost_factor": 1.0,
        "airport": "Goa (GOI)", "hotel_area": "Calangute-Baga belt",
        "peak": [12, 1, 5], "low": [6, 7, 8, 9],
        "rain": [2, 1, 2, 4, 12, 78, 92, 88, 70, 35, 15, 5],
        "tmax": [32, 32, 33, 33, 33, 30, 29, 29, 30, 32, 33, 33],
        "tmin": [21, 22, 24, 26, 27, 25, 24, 24, 24, 24, 23, 22],
        "wikivoyage": "Goa",
        "places": [
            _p("goa-baga", "Baga Beach", ["beach", "nature", "nightlife"], True, 0, 2.5, "any",
               "Goa's busiest beach: shacks, music and sunset."),
            _p("goa-aguada", "Fort Aguada and lighthouse", ["history", "nature"], True, 50, 1.5, "morning",
               "17th-century Portuguese fort with sea views."),
            _p("goa-basilica", "Basilica of Bom Jesus and Se Cathedral", ["history", "culture", "spiritual"],
               False, 0, 1.5, "morning", "UNESCO-listed churches in Old Goa."),
            _p("goa-fontainhas", "Fontainhas Latin Quarter walk", ["culture", "history", "food"], True, 0, 2,
               "afternoon", "Painted Portuguese-era lanes and cafes in Panjim."),
            _p("goa-spice", "Spice plantation tour with lunch", ["food", "nature", "culture"], True, 600, 3,
               "morning", "Guided walk through spice farms, Goan lunch included."),
            _p("goa-cruise", "Mandovi river sunset cruise", ["nightlife", "culture", "relaxation"], True, 500, 1.5,
               "evening", "Evening boat cruise with live music and folk dance."),
            _p("goa-vagator", "Vagator Beach sunset", ["beach", "nature"], True, 0, 2, "evening",
               "Cliff-backed beach, good for sunset."),
            _p("goa-water", "Water sports at Calangute", ["adventure", "beach"], True, 1500, 2, "morning",
               "Parasailing, jet ski and banana-boat rides."),
            _p("goa-anjuna", "Anjuna cafes and market stalls", ["shopping", "food", "nightlife"], True, 0, 2.5,
               "afternoon", "Hippie-era beach town: cafes, stalls, street food."),
            _p("goa-seafood", "Goan seafood thali at a local shack", ["food"], False, 600, 1.5, "any",
               "Fish curry rice, recheado and bebinca."),
            _p("goa-palolem", "Palolem Beach (South Goa)", ["beach", "nature", "relaxation"], True, 0, 3, "any",
               "Calm crescent beach with kayaking and cafes."),
            _p("goa-temple", "Shri Mangueshi Temple", ["spiritual", "culture"], False, 0, 1, "morning",
               "Neo-Goan style temple complex."),
            _p("goa-aviation", "Naval Aviation Museum, Bogmalo", ["history", "family"], False, 100, 1.5,
               "afternoon", "Aircraft and naval aviation exhibits."),
            _p("goa-spa", "Ayurvedic spa session", ["relaxation"], False, 1800, 2, "afternoon",
               "Massage and wellness treatment."),
        ],
    },
    "jaipur": {
        "name": "Jaipur", "lat": 26.91, "lon": 75.79, "cost_factor": 0.9,
        "airport": "Jaipur (JAI)", "hotel_area": "near MI Road / Old City",
        "peak": [10, 11, 12, 1, 2, 3], "low": [5, 6, 7, 8],
        "rain": [8, 8, 6, 5, 10, 25, 55, 60, 32, 8, 3, 5],
        "tmax": [22, 25, 31, 37, 41, 40, 35, 33, 34, 34, 29, 24],
        "tmin": [8, 11, 16, 22, 27, 28, 26, 25, 24, 19, 13, 9],
        "wikivoyage": "Jaipur",
        "places": [
            _p("jp-amber", "Amber Fort", ["history", "culture"], True, 550, 3, "morning",
               "Hilltop Rajput fort-palace with mirror work."),
            _p("jp-citypalace", "City Palace museum", ["history", "culture"], False, 700, 2, "any",
               "Royal residence with textiles, arms and courtyards."),
            _p("jp-hawamahal", "Hawa Mahal", ["history", "culture"], True, 200, 1, "morning",
               "The 'Palace of Winds' facade."),
            _p("jp-jantar", "Jantar Mantar observatory", ["history", "culture"], True, 200, 1.5, "afternoon",
               "UNESCO 18th-century astronomical instruments."),
            _p("jp-nahargarh", "Nahargarh Fort sunset", ["history", "nature"], True, 200, 2, "evening",
               "Ridge-top fort with a city panorama."),
            _p("jp-chokhi", "Chokhi Dhani village dinner and folk show", ["food", "culture", "family"], True, 1100,
               3, "evening", "Rajasthani thali with puppets and dance."),
            _p("jp-johari", "Johari and Bapu Bazaar", ["shopping", "culture", "food"], True, 0, 2.5, "any",
               "Jewellery, textiles and lac bangles."),
            _p("jp-albert", "Albert Hall Museum", ["culture", "history"], False, 40, 1.5, "afternoon",
               "Indo-Saracenic museum building and collections."),
            _p("jp-streetfood", "Old-city street food walk", ["food"], True, 400, 2, "afternoon",
               "Pyaaz kachori, ghewar and lassi stops."),
            _p("jp-jalmahal", "Jal Mahal viewpoint and Kanak Vrindavan", ["nature", "relaxation"], True, 0, 1.5,
               "any", "Palace in the middle of Man Sagar lake."),
            _p("jp-galtaji", "Galta Ji temple complex", ["spiritual", "nature", "culture"], True, 50, 2,
               "morning", "Pilgrim pools set among hills."),
            _p("jp-birla", "Birla Mandir", ["spiritual"], False, 0, 1, "evening",
               "Marble temple, lovely when lit up."),
            _p("jp-blockprint", "Block-printing workshop, Sanganer", ["culture", "shopping"], False, 800, 2.5,
               "afternoon", "Hands-on hand-block printing class."),
        ],
    },
    "manali": {
        "name": "Manali", "lat": 31.88, "lon": 77.15, "cost_factor": 1.0,
        "airport": "Kullu-Manali (KUU), then ~50 km by road", "hotel_area": "Old Manali / Mall Road",
        "peak": [12, 1, 5, 6], "low": [7, 8, 9],
        "rain": [18, 22, 28, 25, 22, 30, 55, 60, 35, 12, 8, 12],
        "tmax": [10, 12, 17, 22, 26, 27, 24, 23, 23, 21, 16, 12],
        "tmin": [-3, -1, 3, 7, 10, 13, 15, 15, 11, 5, 0, -2],
        "wikivoyage": "Manali",
        "places": [
            _p("mn-solang", "Solang Valley (paragliding / zorbing)", ["adventure", "nature"], True, 1200, 3,
               "morning", "Alpine meadow with adventure activities."),
            _p("mn-hadimba", "Hadimba Devi Temple and cedar forest", ["spiritual", "nature", "culture"], True, 0,
               1.5, "morning", "Wooden pagoda temple in deodar woods."),
            _p("mn-oldmanali", "Old Manali cafes and riverside walk", ["food", "relaxation", "nightlife"], True,
               0, 2.5, "any", "Backpacker cafes along the Manalsu."),
            _p("mn-vashisht", "Vashisht hot springs and temple", ["spiritual", "relaxation", "nature"], True, 50,
               2, "afternoon", "Natural sulphur springs village."),
            _p("mn-jogini", "Jogini Waterfall walk", ["adventure", "nature"], True, 0, 3, "morning",
               "Short trek to a waterfall above Vashisht."),
            _p("mn-mall", "Mall Road stroll", ["shopping", "food"], True, 0, 2, "evening",
               "Woollens, Tibetan snacks and street stalls."),
            _p("mn-rafting", "River rafting on the Beas", ["adventure"], True, 1200, 2.5, "afternoon",
               "Grade II-III rafting (seasonal)."),
            _p("mn-manu", "Manu Temple and village walk", ["spiritual", "culture"], True, 0, 1.5, "afternoon",
               "Quiet temple above Old Manali."),
            _p("mn-tibetan", "Tibetan monastery and momos", ["culture", "spiritual", "food"], False, 100, 1.5,
               "any", "Gadhan Thekchhokling gompa."),
            _p("mn-museum", "Museum of Himachal Culture and Folk Art", ["culture", "history"], False, 50, 1.5,
               "afternoon", "Local crafts, costumes and artefacts."),
            _p("mn-naggar", "Naggar Castle and Roerich Art Gallery", ["history", "culture"], False, 100, 2.5,
               "morning", "Medieval castle and the Roerich estate."),
            _p("mn-bonfire", "Campsite bonfire and live music", ["nightlife", "relaxation"], True, 800, 3,
               "evening", "Evening around the fire by the river."),
        ],
    },
    "kochi": {
        "name": "Kochi", "lat": 9.93, "lon": 76.27, "cost_factor": 0.9,
        "airport": "Kochi (COK)", "hotel_area": "Fort Kochi / Ernakulam",
        "peak": [12, 1, 2], "low": [6, 7, 8],
        "rain": [5, 6, 12, 28, 55, 88, 92, 82, 60, 65, 40, 12],
        "tmax": [32, 32, 33, 33, 32, 29, 28, 29, 29, 30, 31, 32],
        "tmin": [23, 24, 25, 26, 26, 24, 24, 24, 24, 24, 24, 23],
        "wikivoyage": "Kochi",
        "places": [
            _p("kc-nets", "Chinese fishing nets at sunset", ["culture", "nature"], True, 0, 1.5, "evening",
               "Cantilevered nets along Fort Kochi beach."),
            _p("kc-mattancherry", "Mattancherry (Dutch) Palace", ["history", "culture"], False, 20, 1.5,
               "morning", "Kerala murals inside a 16th-century palace."),
            _p("kc-jewtown", "Jew Town and Paradesi Synagogue", ["history", "culture", "shopping"], False, 50,
               2, "afternoon", "Antique shops and India's oldest active synagogue."),
            _p("kc-kathakali", "Kathakali performance", ["culture"], False, 400, 2, "evening",
               "Classical dance-drama with make-up viewing."),
            _p("kc-backwaters", "Backwater canoe cruise", ["nature", "relaxation"], True, 1500, 3, "morning",
               "Village canals and coconut groves."),
            _p("kc-hillpalace", "Hill Palace Museum, Tripunithura", ["history", "culture"], False, 50, 2,
               "afternoon", "Former royal palace museum."),
            _p("kc-marine", "Marine Drive promenade", ["relaxation", "nature"], True, 0, 1.5, "evening",
               "Waterfront walk in Ernakulam."),
            _p("kc-cherai", "Cherai Beach", ["beach", "relaxation", "nature"], True, 0, 3, "afternoon",
               "Quiet beach with backwater views."),
            _p("kc-stfrancis", "St. Francis Church and Santa Cruz Basilica", ["history", "spiritual"], False, 0,
               1.5, "morning", "Vasco da Gama's first burial place and a Gothic basilica."),
            _p("kc-sadya", "Kerala sadya / seafood lunch", ["food"], False, 500, 1.5, "any",
               "Banana-leaf meal or karimeen fry."),
            _p("kc-spice", "Spice market tour and tasting", ["food", "shopping", "culture"], True, 300, 2,
               "morning", "Cardamom, pepper and ginger stalls in Mattancherry."),
            _p("kc-folklore", "Kerala Folklore Museum", ["culture"], False, 200, 1.5, "afternoon",
               "Wooden architecture and folk-art collection."),
        ],
    },
    "udaipur": {
        "name": "Udaipur", "lat": 24.58, "lon": 73.71, "cost_factor": 1.0,
        "airport": "Udaipur (UDR)", "hotel_area": "near Lake Pichola",
        "peak": [10, 11, 12, 1, 2, 3], "low": [5, 6, 7, 8],
        "rain": [5, 5, 4, 3, 8, 28, 60, 65, 35, 8, 3, 4],
        "tmax": [25, 28, 33, 38, 41, 38, 32, 30, 32, 34, 30, 26],
        "tmin": [10, 13, 18, 23, 27, 27, 25, 24, 23, 19, 14, 11],
        "wikivoyage": "Udaipur",
        "places": [
            _p("ud-citypalace", "City Palace Udaipur", ["history", "culture"], False, 400, 2.5, "morning",
               "Sprawling lakeside palace-museum."),
            _p("ud-pichola", "Lake Pichola boat ride", ["nature", "relaxation", "culture"], True, 500, 1, "evening",
               "Sunset boat ride past Jag Mandir."),
            _p("ud-jagdish", "Jagdish Temple", ["spiritual", "culture"], False, 0, 1, "morning",
               "Indo-Aryan temple in the old city."),
            _p("ud-saheliyon", "Saheliyon-ki-Bari gardens", ["nature", "culture"], True, 50, 1.5, "morning",
               "Fountain gardens built for royal ladies."),
            _p("ud-sajjangarh", "Sajjangarh (Monsoon) Palace sunset", ["history", "nature"], True, 300, 2,
               "evening", "Hilltop palace with valley views."),
            _p("ud-bagore", "Bagore Ki Haveli folk dance show", ["culture"], False, 150, 1.5, "evening",
               "Evening dharohar dance performance."),
            _p("ud-fatehsagar", "Fateh Sagar Lake promenade", ["relaxation", "nature", "food"], True, 0, 2,
               "evening", "Lakeside snacks and sunset walk."),
            _p("ud-shilpgram", "Shilpgram craft village", ["culture", "shopping"], True, 50, 2.5, "afternoon",
               "Rural arts and crafts of western India."),
            _p("ud-carmuseum", "Vintage Car Museum", ["history", "family"], False, 500, 1.5, "afternoon",
               "Maharana's classic car collection."),
            _p("ud-hathipol", "Hathi Pol bazaar", ["shopping", "food"], True, 0, 2, "afternoon",
               "Miniature paintings, textiles and puppets."),
            _p("ud-cooking", "Rajasthani cooking class", ["food", "culture"], False, 1500, 3, "afternoon",
               "Cook dal-baati and laal maas with a local host."),
            _p("ud-ambrai", "Ambrai Ghat lakeside dinner", ["food", "relaxation", "nightlife"], True, 800, 2,
               "evening", "Dinner with a view of the lit-up City Palace."),
            _p("ud-eklingji", "Eklingji and Nagda temples", ["spiritual", "history"], True, 0, 2.5, "morning",
               "Thousand-year-old temple clusters outside the city."),
        ],
    },
}

# Approximate map positions of the curated landmarks (for the map only; never used for prices or timings).
# Experiences without one fixed spot (a spa session, a food walk) have no entry and are not plotted.
_COORDS = """
goa-baga 15.556 73.752; goa-aguada 15.492 73.774; goa-basilica 15.501 73.912; goa-fontainhas 15.496 73.832
goa-vagator 15.598 73.734; goa-water 15.544 73.755; goa-anjuna 15.574 73.740; goa-palolem 15.010 74.023
goa-temple 15.445 73.968; goa-aviation 15.376 73.839; goa-cruise 15.501 73.830
jp-amber 26.986 75.851; jp-citypalace 26.926 75.824; jp-hawamahal 26.924 75.827; jp-jantar 26.925 75.825
jp-nahargarh 26.937 75.816; jp-chokhi 26.767 75.836; jp-johari 26.920 75.826; jp-albert 26.912 75.820
jp-jalmahal 26.954 75.846; jp-galtaji 26.917 75.858; jp-birla 26.892 75.816
mn-solang 32.317 77.157; mn-hadimba 32.248 77.181; mn-oldmanali 32.254 77.176; mn-vashisht 32.263 77.188
mn-mall 32.243 77.189; mn-manu 32.255 77.175; mn-naggar 32.113 77.165
kc-nets 9.969 76.242; kc-mattancherry 9.958 76.259; kc-jewtown 9.957 76.260; kc-hillpalace 9.953 76.364
kc-marine 9.977 76.275; kc-cherai 10.142 76.178; kc-stfrancis 9.966 76.241
ud-citypalace 24.576 73.684; ud-pichola 24.572 73.679; ud-jagdish 24.579 73.684; ud-saheliyon 24.604 73.690
ud-sajjangarh 24.594 73.639; ud-bagore 24.580 73.682; ud-fatehsagar 24.600 73.678; ud-shilpgram 24.603 73.656
ud-hathipol 24.587 73.690; ud-ambrai 24.579 73.680; ud-eklingji 24.746 73.721
"""
COORDS = {pid: (float(lat), float(lon)) for pid, lat, lon in
          (item.split() for line in _COORDS.strip().splitlines() for item in line.split(";"))}


def coordinates(place_id: str) -> dict:
    """{'lat': .., 'lon': ..} for a curated landmark, else {}."""
    pos = COORDS.get(place_id)
    return {"lat": pos[0], "lon": pos[1]} if pos else {}


# Generic indoor fallback used when rain removes every compatible outdoor option.
GENERIC_INDOOR = {
    "id": "generic-indoor", "name": "Indoor downtime: cafe, spa or local museum", "tags": ["relaxation"],
    "outdoor": False, "cost": 0, "hours": 2, "slot": "any",
    "desc": "Flexible rain-day block; pay only for what you choose.",
}

# City coordinates for the flight estimator (origins + destinations).
CITIES = {
    "delhi": ("Delhi", 28.61, 77.21),
    "mumbai": ("Mumbai", 19.08, 72.88),
    "bengaluru": ("Bengaluru", 12.97, 77.59),
    "hyderabad": ("Hyderabad", 17.39, 78.49),
    "chennai": ("Chennai", 13.08, 80.27),
    "kolkata": ("Kolkata", 22.57, 88.36),
    "pune": ("Pune", 18.52, 73.86),
    "ahmedabad": ("Ahmedabad", 23.02, 72.57),
    "lucknow": ("Lucknow", 26.85, 80.95),
    "goa": ("Goa", 15.38, 73.83),
    "jaipur": ("Jaipur", 26.91, 75.79),
    "manali": ("Manali", 31.88, 77.15),
    "kochi": ("Kochi", 9.93, 76.27),
    "udaipur": ("Udaipur", 24.58, 73.71),
}

ALIASES = {
    "delhi": ["delhi", "new delhi", "ncr", "delhi ncr", "gurgaon", "gurugram", "noida"],
    "mumbai": ["mumbai", "bombay"],
    "bengaluru": ["bengaluru", "bangalore", "blr"],
    "hyderabad": ["hyderabad"],
    "chennai": ["chennai", "madras"],
    "kolkata": ["kolkata", "calcutta"],
    "pune": ["pune"],
    "ahmedabad": ["ahmedabad"],
    "lucknow": ["lucknow"],
    "goa": ["goa"],
    "jaipur": ["jaipur", "pink city"],
    "manali": ["manali"],
    "kochi": ["kochi", "cochin", "fort kochi"],
    "udaipur": ["udaipur"],
}

SUPPORTED_DESTINATIONS = sorted(DESTINATIONS)
SUPPORTED_ORIGINS = sorted(CITIES)


def dest_name(slug: str) -> str:
    return CITIES.get(slug, (slug.title(),))[0]


def place_name(constraints: dict, role: str) -> str:
    """Display name of the origin/destination: resolved place if present, else the curated name."""
    g = constraints.get(f"{role}_geo")
    return g["name"] if g else dest_name(constraints[role])


def dest_cost_factor(constraints: dict) -> float:
    """Price level of the destination (curated value or the resolved place's country-based estimate)."""
    g = constraints.get("destination_geo")
    return g["cost_factor"] if g else DESTINATIONS[constraints["destination"]]["cost_factor"]
