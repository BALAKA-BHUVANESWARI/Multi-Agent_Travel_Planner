"""Slow-changing country facts for the travel companion: money, road side, plugs, phone code, etiquette.

Hand-entered general knowledge, not fetched from an official register, so the page tells the traveller to
check what matters. Etiquette entries are kept to widely documented basics. Nothing here is about visas or
entry rules: those change and must come from official sources (see documents.py).
"""
from __future__ import annotations

# code -> (currency, drives on, usual plug types, dialling code)
FACTS: dict[str, tuple[str, str, str, str]] = {
    "IN": ("Indian rupee (INR)", "left", "C, D, M", "+91"),
    "NP": ("Nepalese rupee (NPR)", "left", "C, D, M", "+977"),
    "BT": ("Bhutanese ngultrum (BTN)", "left", "C, D, G", "+975"),
    "BD": ("Bangladeshi taka (BDT)", "left", "C, D, G, K", "+880"),
    "LK": ("Sri Lankan rupee (LKR)", "left", "D, G, M", "+94"),
    "MV": ("Maldivian rufiyaa (MVR)", "left", "D, G", "+960"),
    "TH": ("Thai baht (THB)", "left", "A, B, C, O", "+66"),
    "SG": ("Singapore dollar (SGD)", "left", "G", "+65"),
    "MY": ("Malaysian ringgit (MYR)", "left", "G", "+60"),
    "ID": ("Indonesian rupiah (IDR)", "left", "C, F", "+62"),
    "VN": ("Vietnamese dong (VND)", "right", "A, C", "+84"),
    "KH": ("Cambodian riel (KHR); US dollars are widely used", "right", "A, C, G", "+855"),
    "LA": ("Lao kip (LAK)", "right", "A, B, C, E, F", "+856"),
    "MM": ("Myanmar kyat (MMK)", "right", "A, C, D, G", "+95"),
    "PH": ("Philippine peso (PHP)", "right", "A, B, C", "+63"),
    "JP": ("Japanese yen (JPY)", "left", "A, B", "+81"),
    "KR": ("South Korean won (KRW)", "right", "C, F", "+82"),
    "CN": ("Chinese yuan (CNY)", "right", "A, C, I", "+86"),
    "HK": ("Hong Kong dollar (HKD)", "left", "G", "+852"),
    "MO": ("Macanese pataca (MOP)", "left", "G", "+853"),
    "TW": ("New Taiwan dollar (TWD)", "right", "A, B", "+886"),
    "AE": ("UAE dirham (AED)", "right", "G", "+971"),
    "QA": ("Qatari riyal (QAR)", "right", "D, G", "+974"),
    "OM": ("Omani rial (OMR)", "right", "G", "+968"),
    "JO": ("Jordanian dinar (JOD)", "right", "C, G", "+962"),
    "TR": ("Turkish lira (TRY)", "right", "C, F", "+90"),
    "EG": ("Egyptian pound (EGP)", "right", "C, F", "+20"),
    "MA": ("Moroccan dirham (MAD)", "right", "C, E", "+212"),
    "ZA": ("South African rand (ZAR)", "left", "C, D, M, N", "+27"),
    "KE": ("Kenyan shilling (KES)", "left", "G", "+254"),
    "TZ": ("Tanzanian shilling (TZS)", "left", "D, G", "+255"),
    "MU": ("Mauritian rupee (MUR)", "left", "C, G", "+230"),
    "GB": ("Pound sterling (GBP)", "left", "G", "+44"),
    "IE": ("Euro (EUR)", "left", "G", "+353"),
    "FR": ("Euro (EUR)", "right", "C, E", "+33"),
    "IT": ("Euro (EUR)", "right", "C, F, L", "+39"),
    "ES": ("Euro (EUR)", "right", "C, F", "+34"),
    "PT": ("Euro (EUR)", "right", "C, F", "+351"),
    "NL": ("Euro (EUR)", "right", "C, F", "+31"),
    "BE": ("Euro (EUR)", "right", "C, E", "+32"),
    "DE": ("Euro (EUR)", "right", "C, F", "+49"),
    "AT": ("Euro (EUR)", "right", "C, F", "+43"),
    "GR": ("Euro (EUR)", "right", "C, F", "+30"),
    "HR": ("Euro (EUR)", "right", "C, F", "+385"),
    "CZ": ("Czech koruna (CZK)", "right", "C, E", "+420"),
    "HU": ("Hungarian forint (HUF)", "right", "C, F", "+36"),
    "CH": ("Swiss franc (CHF)", "right", "C, J", "+41"),
    "DK": ("Danish krone (DKK)", "right", "C, E, F, K", "+45"),
    "SE": ("Swedish krona (SEK)", "right", "C, F", "+46"),
    "NO": ("Norwegian krone (NOK)", "right", "C, F", "+47"),
    "IS": ("Icelandic krona (ISK)", "right", "C, F", "+354"),
    "PL": ("Polish zloty (PLN)", "right", "C, E", "+48"),
    "US": ("US dollar (USD)", "right", "A, B", "+1"),
    "CA": ("Canadian dollar (CAD)", "right", "A, B", "+1"),
    "MX": ("Mexican peso (MXN)", "right", "A, B", "+52"),
    "BR": ("Brazilian real (BRL)", "right", "C, N", "+55"),
    "AR": ("Argentine peso (ARS)", "right", "C, I", "+54"),
    "PE": ("Peruvian sol (PEN)", "right", "A, B, C", "+51"),
    "AU": ("Australian dollar (AUD)", "left", "I", "+61"),
    "NZ": ("New Zealand dollar (NZD)", "left", "I", "+64"),
}

GENERAL_CUSTOMS = [
    "Dress modestly at places of worship, and follow the signs about shoes, head covering and photography.",
    "Ask before photographing people.",
    "Learn a greeting and 'thank you' in the local language.",
]
_EUROPE = ["Cover shoulders and knees when visiting churches and cathedrals.",
           "Watch your bags and pockets on public transport and around major sights."]
_GULF = ["Dress modestly in public places such as markets, malls and old quarters.",
         "Keep public displays of affection to a minimum.",
         "Drink alcohol only where it is licensed.",
         "Ask before photographing people, and do not photograph government or military sites."]

CUSTOMS: dict[str, list[str]] = {
    "IN": ["Take your shoes off before entering temples, gurdwaras, mosques and many homes.",
           "Cover your head in gurdwaras, and dress modestly at any religious site.",
           "Some temples do not allow phones or cameras: check the signs.",
           "Use your right hand to give, take and eat."],
    "NP": ["Walk clockwise around stupas and shrines.", "Remove your shoes before entering temples and homes.",
           "Some temples do not admit visitors of other faiths."],
    "BT": ["Dress formally, with long sleeves and long trousers or skirts, at dzongs and temples.",
           "Walk clockwise around chortens and prayer walls."],
    "LK": ["Remove shoes and hats and cover shoulders and knees at temples.",
           "Never pose for a photo with your back to a Buddha statue."],
    "MV": ["Outside the resorts, dress modestly; wear swimwear only on beaches set aside for it.",
           "Alcohol is limited to resorts and similar licensed places; do not bring alcohol or pork into the "
           "country."],
    "TH": ["Never insult the monarchy: it is a serious criminal offence.",
           "Cover shoulders and knees and remove your shoes at temples.",
           "Do not touch people's heads or point your feet at people or Buddha images."],
    "SG": ["Littering and similar offences carry heavy fines.",
           "Do not bring chewing gum or vaping devices: both are restricted."],
    "MY": ["Remove your shoes before entering homes and places of worship.",
           "Dress modestly at mosques, and use your right hand to give and take."],
    "ID": ["At Balinese temples wear a sarong and sash.", "Dress modestly away from beach areas.",
           "Use your right hand to give and take."],
    "VN": ["Dress modestly at pagodas and temples.", "Do not photograph military sites."],
    "KH": ["Cover shoulders and knees at temples, including Angkor.", "Do not touch people's heads."],
    "LA": ["Cover shoulders and knees and remove your shoes at temples.", "Do not touch people's heads."],
    "MM": ["Remove shoes and socks at pagodas, and dress modestly."],
    "JP": ["Take your shoes off where you see a raised entrance or slippers.", "Tipping is not customary.",
           "Keep your voice down and avoid phone calls on trains.",
           "Many public baths do not admit people with visible tattoos."],
    "KR": ["Give and receive things with both hands, especially with older people.",
           "Take your shoes off indoors."],
    "CN": ["Many foreign apps and websites are blocked: plan how you will stay in touch.",
           "Do not photograph military or police sites."],
    "AE": _GULF, "QA": _GULF, "OM": _GULF,
    "JO": ["Dress modestly, especially away from resorts.", "Ask before photographing people."],
    "TR": ["At mosques remove your shoes and cover shoulders and knees; women cover their hair."],
    "EG": ["Dress modestly away from resorts.", "Small tips are expected for many services.",
           "Ask before photographing people."],
    "MA": ["Dress modestly.", "Many mosques are closed to non-Muslims.", "Ask before photographing people."],
    "US": ["Tipping in restaurants and taxis is expected."],
    "CA": ["Tipping in restaurants and taxis is customary."],
    "IT": _EUROPE + ["Some cities fine people for sitting on certain monuments and steps: check the signs."],
    "FR": _EUROPE + ["Say 'bonjour' when you walk into a shop or start a conversation."],
    "DE": _EUROPE + ["Carry some cash: not every place takes cards."],
}
for _code in ("ES", "PT", "NL", "BE", "AT", "CH", "CZ", "HU", "GR", "HR", "PL"):
    CUSTOMS.setdefault(_code, _EUROPE)

# Countries known for strict rules on bringing in some ordinary medicines.
STRICT_MEDICINE = {"AE", "QA", "OM", "JP", "SG", "ID"}


def useful_info(cc: str) -> dict | None:
    facts = FACTS.get((cc or "").upper())
    if not facts:
        return None
    currency, side, plugs, dial = facts
    return {"currency": currency, "drives_on": side, "plug_types": plugs, "dialling_code": dial}


def customs_for(cc: str) -> dict:
    specific = CUSTOMS.get((cc or "").upper())
    return {"specific": bool(specific), "tips": list(specific or GENERAL_CUSTOMS)}
