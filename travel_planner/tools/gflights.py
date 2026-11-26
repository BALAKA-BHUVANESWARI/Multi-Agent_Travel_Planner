"""Google Flights search URLs (the ``tfs`` parameter) for live-fare lookups.

``tfs`` is a URL-safe base64 protobuf: trip legs (date, origin, destination), passengers and cabin. This module
writes the few fields a round-trip search needs. ``build_tfs`` reproduces, byte for byte, the example in Bright
Data's Google Flights docs (see tests/test_live_probe.py), so the layout is checked against a real, published value.
"""
from __future__ import annotations

import base64
from urllib.parse import urlencode

AIRPORT, CITY = 1, 3                       # place types: an IATA airport code, or a city's Freebase id (/m/...)
_FOOTER = bytes.fromhex("82010b08ffffffffffffffffff01")   # constant block seen in real Google Flights links


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, wire: int, payload: bytes) -> bytes:
    return _varint((num << 3) | wire) + payload


def _bytes_field(num: int, data: bytes) -> bytes:
    return _field(num, 2, _varint(len(data)) + data)


def _place(kind: int, ident: str) -> bytes:
    return _field(1, 0, _varint(kind)) + _bytes_field(2, ident.encode())


def _leg(date: str, origin: tuple[int, str], dest: tuple[int, str]) -> bytes:
    return _bytes_field(3, _bytes_field(2, date.encode()) + _bytes_field(13, _place(*origin))
                        + _bytes_field(14, _place(*dest)))


def build_tfs(origin: tuple[int, str], dest: tuple[int, str], depart: str, ret: str | None, adults: int = 1) -> str:
    """Round trip when ``ret`` is given, otherwise one way. Dates are YYYY-MM-DD; economy cabin."""
    if not 1 <= adults <= 9:
        raise ValueError("adults must be 1-9")
    body = _field(1, 0, _varint(28)) + _field(2, 0, _varint(2)) + _leg(depart, origin, dest)
    if ret:
        body += _leg(ret, dest, origin)
    body += _field(8, 0, _varint(1)) * adults + _field(9, 0, _varint(1)) + _field(14, 0, _varint(1)) + _FOOTER
    body += _field(19, 0, _varint(1 if ret else 2))
    return base64.urlsafe_b64encode(body).decode().rstrip("=")


def flights_url(origin: tuple[int, str], dest: tuple[int, str], depart: str, ret: str | None, adults: int = 1,
                currency: str = "INR", country: str = "in", lang: str = "en") -> str:
    q = urlencode({"tfs": build_tfs(origin, dest, depart, ret, adults), "curr": currency, "gl": country,
                   "hl": lang})
    return "https://www.google.com/travel/flights/search?" + q
