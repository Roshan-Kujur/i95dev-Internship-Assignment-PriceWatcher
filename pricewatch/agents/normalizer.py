# """Normalizer agent: turns whatever a page printed into (minor units, ISO currency).

# Storefronts print money in a dozen ways. Everything downstream (history, alerts, the
# dashboard) assumes `price_cents` is an int in the store's currency. This is the only place
# that should know about currency symbols and locale formatting.
# """
# from __future__ import annotations

# import re
# from typing import Optional

# SYMBOLS = {
#     "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "kr": "SEK", "¥": "JPY", "CHF": "CHF",
# }
# CODES = {"USD", "EUR", "GBP", "INR", "SEK", "NOK", "DKK", "JPY", "CHF", "CAD", "AUD"}


# def detect_currency(text: str, default: Optional[str] = None) -> Optional[str]:
#     t = text.strip()
#     for code in CODES:
#         if re.search(rf"\b{code}\b", t):
#             return code
#     for sym, code in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
#         if sym in t:
#             return code
#     return default


# def parse_money(text: str, default_currency: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
#     """Parse a printed price like "$1,299.00" into (129900, "USD").

#     Returns (None, currency) when no number is present.
#     """
#     if text is None:
#         return None, default_currency
#     currency = detect_currency(text, default_currency)
#     digits = re.sub(r"[^\d.]", "", text)
#     if not digits or digits == ".":
#         return None, currency
#     try:
#         amount = float(digits)
#     except ValueError:
#         return None, currency
#     return int(round(amount * 100)), currency


# def unit_price(price_cents: Optional[int], pack_size: int) -> Optional[int]:
#     if price_cents is None or pack_size <= 1:
#         return None
#     return int(round(price_cents / pack_size))

# ------------------Normaliser New Updates --------------------


"""Normalizer agent: turns whatever a page printed into (minor units, ISO currency).

Storefronts print money in a dozen ways. Everything downstream (history, alerts, the
dashboard) assumes `price_cents` is an int in the store's currency. This is the only place
that should know about currency symbols and locale formatting.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

SYMBOLS = {
    "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "kr": "SEK", "¥": "JPY", "CHF": "CHF",
}
CODES = {"USD", "EUR", "GBP", "INR", "SEK", "NOK", "DKK", "JPY", "CHF", "CAD", "AUD"}

# The first number in the text: digits, with dots, commas, spaces (incl. non-breaking) and
# apostrophes (Swiss thousands mark, as in CHF 1'299.50) inside.
_NUM = re.compile(r"\d[\d.,\s\u00a0\u202f'\u2019\u02bc]*")
_SPACES = re.compile(r"[\s\u00a0\u202f'\u2019\u02bc]")  # thousands separators that are just dropped
_NON_DIGIT = re.compile(r"\D")


def detect_currency(text: str, default: Optional[str] = None) -> Optional[str]:
    t = text.strip()
    for code in CODES:
        if re.search(rf"\b{code}\b", t):
            return code
    for sym, code in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if sym in t:
            return code
    return default


def _to_amount(text: str) -> Optional[Decimal]:
    """Read the number in a printed price, whether it uses 1,299.00 or 1.299,00 style."""
    m = _NUM.search(text)
    if not m:
        return None
    num = _SPACES.sub("", m.group()).rstrip(".,")
    if not num:
        return None

    last_dot, last_comma = num.rfind("."), num.rfind(",")
    if last_dot != -1 and last_comma != -1:
        # Both marks present: the one that comes last is the decimal mark.
        dec = "." if last_dot > last_comma else ","
    else:
        sep = "." if last_dot != -1 else "," if last_comma != -1 else None
        if sep is None:
            dec = None                                   # no mark at all: whole number
        elif num.count(sep) > 1:
            dec = None                                   # repeated mark: thousands marks
        elif len(num) - num.rfind(sep) - 1 == 3:
            dec = None                                   # exactly 3 digits after it: thousands mark
        else:
            dec = sep                                    # 98,72 or 12.99: decimal mark

    if dec is None:
        return Decimal(_NON_DIGIT.sub("", num))
    whole, frac = num.rsplit(dec, 1)
    whole_digits = _NON_DIGIT.sub("", whole) or "0"
    frac_digits = _NON_DIGIT.sub("", frac)
    return Decimal(f"{whole_digits}.{frac_digits}")


def parse_money(text: str, default_currency: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
    """Parse a printed price like "$1,299.00" or "98,72 €" into (cents, ISO currency).

    Returns (None, currency) when no number is present.
    """
    if text is None:
        return None, default_currency
    currency = detect_currency(text, default_currency)
    amount = _to_amount(text)
    if amount is None:
        return None, currency
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)), currency


def unit_price(price_cents: Optional[int], pack_size: int) -> Optional[int]:
    if price_cents is None or pack_size <= 1:
        return None
    return int(round(price_cents / pack_size))

