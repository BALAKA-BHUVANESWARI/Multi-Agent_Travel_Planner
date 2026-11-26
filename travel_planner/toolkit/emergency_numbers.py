"""Emergency telephone numbers by ISO country code.

SAFETY RULES for editing this file: never add a number from memory. Take it from a named source, record the
source, and when two government sources disagree show both instead of picking one. A country that is not listed
gets no number at all (the app says so), never a guess.

Checked on CHECKED_ON. Main source: Wikipedia, "List of emergency telephone numbers". India, Sri Lanka and the
Maldives were also checked against government pages. The fire numbers for Singapore, Japan, South Korea, Taiwan
and Morocco were confirmed against a second, undated list on a Columbia University site. A service whose number
the sources did not clearly show is left blank (fire in Belgium, Germany and the Maldives).
"""
from __future__ import annotations

CHECKED_ON = "2026-11-26"
WIKI = ("Wikipedia: List of emergency telephone numbers",
        "https://en.wikipedia.org/wiki/List_of_emergency_telephone_numbers")
IN_GOV = ("India: Emergency Response Support System (112)", "https://112.gov.in/about")
UK_LK = ("UK government travel advice: Sri Lanka", "https://www.gov.uk/foreign-travel-advice/sri-lanka/getting-help")
CA_LK = ("Government of Canada: Sri Lanka", "https://travel.gc.ca/assistance/embassies-consulates/sri-lanka")
COLUMBIA = ("Columbia University: emergency numbers abroad (undated)",
            "https://globaltravel.columbia.edu/sites/globaltravel.columbia.edu/files/content/docs/911_ABROAD.pdf")
UK_MV = ("UK government travel advice: Maldives", "https://gov.uk/foreign-travel-advice/maldives/health")
CA_MV = ("Government of Canada: Maldives", "https://travel.gc.ca/assistance/embassies-consulates/maldives")


NO_FIRE = "No fire number was confirmed from the sources, so none is shown."


def _n(any_: str = "", police: str = "", ambulance: str = "", fire: str = "", extra: tuple = (),
       note: str = "", sources: tuple = (WIKI,)) -> dict:
    return {"any": any_, "police": police, "ambulance": ambulance, "fire": fire,
            "extra": [list(x) for x in extra], "note": note, "sources": [list(s) for s in sources]}


NUMBERS: dict[str, dict] = {
    # South Asia
    "IN": _n("112", "100", "108", "101",
             (("Women's helpline", "181"), ("Child helpline", "1098"), ("Tourist helpline", "1363")),
             "112 is the single national emergency number; 100, 101 and 108 are the older numbers.",
             (IN_GOV, WIKI)),
    "NP": _n("", "100", "102", "101", note="112 also works from mobile phones."),
    "BT": _n("", "113", "112", "110"),
    "BD": _n("999"),
    "LK": _n("", "119 or 118", "1990 or 110", "110 or 111", (("Tourist police", "011 242 1052"),),
             "Government pages differ: for an ambulance the UK gives 1990 and Canada 110; for fire the UK gives "
             "111 and Canada 110.", (UK_LK, CA_LK)),
    "MV": _n("", "119", "102", note=NO_FIRE + " Ask your resort or hotel.", sources=(UK_MV, CA_MV, WIKI)),
    # East and South-East Asia
    "TH": _n("", "191", "1669", "199", (("Tourist police", "1155"),), "112 also works from mobile phones."),
    "SG": _n("", "999", "995", "995", sources=(WIKI, COLUMBIA)),
    "MY": _n("999", note="112 also works from mobile phones."),
    "ID": _n("112", "110", "118 or 119", "113"),
    "VN": _n("", "113", "115", "114"),
    "KH": _n("", "117", "119", "118"),
    "LA": _n("", "191", "195", "190"),
    "MM": _n("999", "199", "192", "191"),
    "PH": _n("911", note="112 also works from mobile phones."),
    "JP": _n("", "110", "119", "119", sources=(WIKI, COLUMBIA)),
    "KR": _n("", "112", "119", "119", (("Travel hotline", "1330"),), sources=(WIKI, COLUMBIA)),
    "CN": _n("", "110", "120", "119"),
    "HK": _n("999"),
    "MO": _n("999"),
    "TW": _n("", "110", "119", "119", sources=(WIKI, COLUMBIA)),
    # West Asia and Africa
    "AE": _n("", "999", "998", "997"),
    "QA": _n("999", note="112 also works from mobile phones."),
    "OM": _n("9999", note="112 also works from mobile phones."),
    "JO": _n("911", note="112 also works from mobile phones."),
    "TR": _n("112"),
    "EG": _n("", "122", "123", "180", (("Tourist police", "126"),), "112 also works from mobile phones."),
    "MA": _n("", "19", "15", "15", (("Royal gendarmerie", "177"),), "112 also works from mobile phones.",
             (WIKI, COLUMBIA)),
    "ZA": _n("", "10111", "10177", note="112 also works from mobile phones."),
    "KE": _n("112, 999 or 911"),
    "TZ": _n("112", "999", "114", "115"),
    "MU": _n("112", "999", "114", "115 or 995"),
    # Europe
    "GB": _n("999 or 112"),
    "IE": _n("112 or 999"),
    "FR": _n("112", "17", "15", "18"),
    "IT": _n("112"),
    "ES": _n("112"),
    "PT": _n("112"),
    "NL": _n("112"),
    "BE": _n("", "101", "112", note=NO_FIRE),
    "DE": _n("", "110", "112", note=NO_FIRE),
    "CZ": _n("112", "158", "155", "150"),
    "AT": _n("112", "133", "144", "122"),
    "HU": _n("112", "107", "104", "105"),
    "CH": _n("", "117", "144", "118"),
    "GR": _n("112", "100", "166", "199"),
    "HR": _n("112", "192", "194", "193"),
    "DK": _n("112"),
    "SE": _n("112"),
    "NO": _n("", "112", "113", "110"),
    "IS": _n("112"),
    "PL": _n("112", "997", "999", "998"),
    # Americas and Oceania
    "US": _n("911"),
    "CA": _n("911"),
    "MX": _n("911"),
    "BR": _n("", "190", "192", "193"),
    "AR": _n("911", "101", "107", "100"),
    "PE": _n("911", "105", "106", "116"),
    "AU": _n("000", note="112 also works from mobile phones."),
    "NZ": _n("111"),
}
