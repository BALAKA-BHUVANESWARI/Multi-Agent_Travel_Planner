"""A hand-tagged list of popular destinations, used for suggestions. The tags and best months are rough,
hand-entered guidance."""
from __future__ import annotations

from app.data import gazetteer
from app.data.curated_destinations import DESTINATIONS
from app.services import geo_service as geo_mod

# slug -> (interests it is known for, best months). List order breaks ties (rough popularity).
PROFILES: dict[str, tuple[tuple[str, ...], tuple[int, ...]]] = {
    "goa": (("beach", "nightlife", "food", "relaxation"), (11, 12, 1, 2, 3)),
    "jaipur": (("history", "culture", "shopping", "food"), (10, 11, 12, 1, 2, 3)),
    "udaipur": (("history", "culture", "relaxation", "food"), (10, 11, 12, 1, 2, 3)),
    "kochi": (("culture", "history", "food", "nature", "relaxation"), (10, 11, 12, 1, 2, 3)),
    "manali": (("adventure", "nature", "relaxation"), (3, 4, 5, 6, 10, 12, 1)),
    "rishikesh": (("adventure", "spiritual", "nature"), (2, 3, 4, 10, 11)),
    "varanasi": (("spiritual", "culture", "history", "food"), (10, 11, 12, 1, 2, 3)),
    "agra": (("history", "culture"), (10, 11, 12, 1, 2, 3)),
    "amritsar": (("spiritual", "history", "food", "culture"), (10, 11, 12, 1, 2, 3)),
    "shimla": (("nature", "relaxation", "family"), (3, 4, 5, 6, 10, 12)),
    "darjeeling": (("nature", "relaxation", "culture"), (3, 4, 5, 10, 11)),
    "gangtok": (("nature", "adventure", "spiritual"), (3, 4, 5, 10, 11)),
    "munnar": (("nature", "relaxation", "family"), (9, 10, 11, 12, 1, 2, 3)),
    "alleppey": (("relaxation", "nature", "food", "family"), (10, 11, 12, 1, 2)),
    "mysuru": (("history", "culture", "family", "shopping"), (10, 11, 12, 1, 2)),
    "hampi": (("history", "culture", "adventure"), (10, 11, 12, 1, 2)),
    "pondicherry": (("beach", "relaxation", "food", "culture"), (10, 11, 12, 1, 2, 3)),
    "ooty": (("nature", "family", "relaxation"), (4, 5, 6, 10, 11)),
    "leh": (("adventure", "nature", "spiritual"), (6, 7, 8, 9)),
    "jaisalmer": (("history", "adventure", "culture"), (11, 12, 1, 2)),
    "shillong": (("nature", "adventure"), (3, 4, 10, 11)),
    "port-blair": (("beach", "nature", "adventure"), (11, 12, 1, 2, 3, 4)),
    "gokarna": (("beach", "relaxation", "spiritual"), (10, 11, 12, 1, 2)),
    "coorg": (("nature", "relaxation", "food"), (9, 10, 11, 12, 1, 2, 3)),
    "varkala": (("beach", "relaxation"), (11, 12, 1, 2, 3)),
    "dharamshala": (("nature", "spiritual", "adventure"), (3, 4, 5, 9, 10, 11)),
    "sawai-madhopur": (("nature", "adventure", "family"), (10, 11, 12, 1, 2, 3, 4)),
    "bangkok": (("food", "shopping", "spiritual", "nightlife", "culture"), (11, 12, 1, 2)),
    "phuket": (("beach", "nightlife", "relaxation"), (11, 12, 1, 2, 3)),
    "bali": (("beach", "nature", "relaxation", "spiritual"), (4, 5, 6, 7, 8, 9)),
    "kathmandu": (("spiritual", "culture", "adventure", "history"), (3, 4, 10, 11)),
    "pokhara": (("adventure", "nature", "relaxation"), (3, 4, 10, 11)),
    "paro": (("spiritual", "nature", "culture"), (3, 4, 5, 9, 10, 11)),
    "kandy": (("culture", "nature", "spiritual"), (1, 2, 3, 4, 7, 8)),
    "hanoi": (("food", "culture", "history"), (10, 11, 3, 4)),
    "da-nang": (("beach", "food", "family"), (2, 3, 4, 5, 6, 7, 8)),
    "siem-reap": (("history", "culture", "spiritual"), (11, 12, 1, 2)),
    "kuala-lumpur": (("food", "shopping", "family"), (5, 6, 7, 12, 1, 2)),
    "singapore": (("family", "food", "shopping", "culture"), (2, 3, 4, 7, 8)),
    "dubai": (("shopping", "family", "adventure", "beach"), (11, 12, 1, 2, 3)),
    "maldives": (("beach", "relaxation", "nature"), (11, 12, 1, 2, 3, 4)),
    "istanbul": (("history", "culture", "food", "shopping"), (4, 5, 9, 10)),
    "tokyo": (("food", "shopping", "culture", "family"), (3, 4, 10, 11)),
    "kyoto": (("history", "culture", "spiritual"), (3, 4, 10, 11)),
    "paris": (("culture", "history", "food", "shopping"), (4, 5, 6, 9, 10)),
    "rome": (("history", "culture", "food", "spiritual"), (4, 5, 6, 9, 10)),
    "interlaken": (("adventure", "nature"), (6, 7, 8, 9, 12, 1, 2)),
    "prague": (("history", "culture", "nightlife"), (4, 5, 6, 9, 10)),
    "barcelona": (("beach", "culture", "nightlife", "food"), (5, 6, 9, 10)),
}


def profile_tags(slug: str) -> list[str]:
    return list(PROFILES.get(slug, ((), ()))[0])


def geo_for(slug: str) -> dict | None:
    if slug in DESTINATIONS:
        return geo_mod.from_catalog(slug)
    entry = gazetteer.lookup(slug.replace("-", " "))
    return geo_mod._from_gazetteer(entry) if entry else None
