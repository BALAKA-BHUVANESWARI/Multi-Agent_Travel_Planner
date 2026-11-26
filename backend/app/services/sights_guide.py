"""Top sights with a label and the best time to visit. Pure code, no network.

"Famous" means prominent in the free sources (Wikipedia, Wikidata, Wikivoyage, OpenStreetMap), carried as `fame`
on each candidate; for hand-curated destinations it is the curated order, which lists the headline sights first.
Timings are general guidance by kind of place, not opening hours: the plan itself already schedules each sight
into the slot that suits it, and the UI shows that planned time next to this advice.
"""
from __future__ import annotations

import re

TOP_N = 8

# (pattern on lower-cased "name + tags + kind", label). First match wins.
_LABELS = [
    (r"\b(waterfall|falls)\b", "Waterfall"),
    (r"\bbeach\b", "Beach"),
    (r"\b(fort|fortress|castle|palace|citadel|mahal|monument|ruins?|tomb|memorial|heritage|historic|history|stables?|dibba|platform|step ?wells?|pushkarani|gate|gateway|mandapa|monolith|stepwell|baoli|haveli)\b",
     "Historical"),
    (r"\b(temple|church|cathedral|mosque|gurudwara|gurdwara|monastery|shrine|stupa|mandir|spiritual|worship)\b",
     "Spiritual"),
    (r"\b(museum|gallery)\b", "Museum"),
    (r"\b(viewpoint|sunset|sunrise|peak|hill|point)\b", "Viewpoint"),
    (r"\b(lake|dam|river|ghat|reserve|park|garden|nature|valley|trail)\b", "Nature"),
    (r"\b(adventure|trek|rafting|paragliding|camp)\b", "Adventure"),
    (r"\b(market|bazaar|shopping)\b", "Market"),
]
_BEST = {
    "Waterfall": ("Morning (8:00-11:00), when the light is good and it is quiet",
                  "Flow is usually strongest after the rainy season"),
    "Beach": ("Early morning, or 16:00-18:30 for the sunset; avoid the midday heat", None),
    "Historical": ("Early morning (8:00-10:00), before the crowds and the heat", None),
    "Spiritual": ("Early morning (6:00-9:00) or around sunset; dress modestly", None),
    "Museum": ("Weekday mornings are quietest; check closing days", None),
    "Viewpoint": ("Sunrise or sunset (check the local times for your dates)", None),
    "Nature": ("Morning (7:00-10:00) or late afternoon (16:00-18:00)", None),
    "Adventure": ("Morning (from about 8:00) for the best conditions and full daylight", None),
    "Market": ("Late afternoon to evening (16:00-21:00), when stalls are busiest", None),
}
_SLOT_FALLBACK = {"morning": "Morning (8:00-11:00)", "afternoon": "Afternoon (13:00-17:00)",
                  "evening": "Late afternoon to sunset (16:00-19:00)", "any": "Any time of day; early morning is quietest"}
_KIND_LABEL = {"museum": "Museum", "gallery": "Museum", "fort": "Historical", "monument": "Historical",
               "worship": "Spiritual", "viewpoint": "Viewpoint", "peak": "Viewpoint", "park": "Nature",
               "reserve": "Nature", "waterfall": "Waterfall", "beach": "Beach", "cave": "Adventure",
               "spring": "Nature", "zoo": "Nature", "market": "Market", "theme_park": "Adventure"}
# a weak hint, tried only when the name, tags and kind say nothing: what the description talks about
_DESC_HINTS = [
    (r"\b(century|empire|dynasty|king|queen|emperor|ruins?|ancient|medieval|british|colonial|mughal|rajput|"
     r"built by|constructed|heritage|unesco|capital of)\b", "Historical"),
    (r"\b(temple|shrine|pilgrim|sacred|deity|worship|monastery)\b", "Spiritual"),
    (r"\b(view|panorama|sunset|sunrise)\b", "Viewpoint"),
    (r"\b(lake|river|forest|wildlife|valley|hill|garden)\b", "Nature"),
]


def label_for(c: dict) -> str:
    text = " ".join([c.get("name", ""), " ".join(c.get("tags", [])), c.get("kind", "") or ""]).lower()
    for pat, label in _LABELS:
        if re.search(pat, text):
            return label
    if c.get("kind") in _KIND_LABEL:
        return _KIND_LABEL[c["kind"]]
    desc = (c.get("desc") or "").lower()
    for pat, label in _DESC_HINTS:
        if re.search(pat, desc):
            return label
    return "Sight"


def best_time_for(c: dict) -> tuple[str, str | None]:
    label = label_for(c)
    if label in _BEST:
        return _BEST[label]
    return _SLOT_FALLBACK.get(c.get("slot", "any"), _SLOT_FALLBACK["any"]), None


def top_sights(cands: list[dict], n: int = TOP_N) -> list[dict]:
    """The most prominent nearby sights, best first, each with a label and when to go. Day trips and the generic
    filler suggestions (walking tour, dinner...) are left out."""
    pool = [(i, c) for i, c in enumerate(cands) if not str(c.get("id", "")).startswith("gen-") and not c.get("far")]
    size = max(1, len(pool))

    def fame(i, c):
        return float(c["fame"]) if isinstance(c.get("fame"), (int, float)) else (size - i) / size * 4
    ordered = sorted(pool, key=lambda ic: (-fame(*ic), ic[0]))[:n]
    out = []
    for rank, (_, c) in enumerate(ordered, 1):
        when, season = best_time_for(c)
        out.append({"rank": rank, "id": c["id"], "name": c["name"], "label": label_for(c), "best_time": when,
                    "season": season, "cost": c.get("cost", 0), "desc": (c.get("desc") or "")[:140]})
    return out


NOTE = ("Ranked by how prominent each place is in Wikipedia, Wikivoyage and OpenStreetMap (free sources have no live "
        "visitor counts). Timings are general advice by kind of place; check local opening hours.")
