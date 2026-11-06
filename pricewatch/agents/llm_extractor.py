# """LLM extractor: the fallback for stores we have no adapter for.

# Given raw HTML and its URL, ask a model for the structured offer.
# """
# from __future__ import annotations

# import json
# import re

# from bs4 import BeautifulSoup

# from ..models import Observation
# from ..providers import Provider

# SYSTEM = """You extract e-commerce offer data from a product page and answer ONLY with a JSON object:
# {"name": str|null, "price_cents": int|null, "currency": "ISO-4217"|null, "availability": "in_stock"|"out_of_stock"|"unknown",
#  "pack_size": int, "compare_at_cents": int|null}
# price_cents is the price of the pack actually being sold, in minor units. If there is no price, use null."""


# def clean_html(html: str, limit: int = 12000) -> str:
#     soup = BeautifulSoup(html, "html.parser")
#     for t in soup(["script", "style", "noscript", "svg"]):
#         t.decompose()
#     text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
#     return text[:limit]


# def extract_with_llm(provider: Provider, store: str, url: str, html: str, timeout: float = 30.0) -> Observation:
#     user = f"URL: {url}\n\nPAGE TEXT:\n{clean_html(html)}"
#     raw = provider.complete(SYSTEM, user, metadata={"source_url": url, "store": store}, timeout=timeout)
#     data = json.loads(raw)
#     return Observation(
#         store=store, product_id=url.rstrip("/").split("/")[-1], url=url, name=data.get("name") or "",
#         price_cents=data.get("price_cents"), currency=data.get("currency") or "",
#         compare_at_cents=data.get("compare_at_cents"), availability=data.get("availability") or "unknown",
#         pack_size=int(data.get("pack_size") or 1), source="llm",
#     )


# -------------------------Modified llm_extractor--------------------------------
# 
# 
"""LLM-based fallback extractor for stores without a dedicated adapter."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..models import Observation
from ..providers import Provider


SYSTEM = """
You are an e-commerce product-page extraction system.

Extract information about the product actually being sold.

Return ONLY one valid JSON object with exactly these fields:
{
  "name": string or null,
  "price_cents": integer or null,
  "currency": string or null,
  "availability": "in_stock" or "out_of_stock" or "unknown",
  "pack_size": positive integer,
  "compare_at_cents": integer or null
}

Rules:
1. price_cents is the TOTAL selling price of the selected product or pack.
2. Convert prices into minor currency units:
   INR 1470.57 -> 147057
   NOK 2926.00 -> 292600
3. Do not use the per-unit price when a total pack price is shown.
4. Do not use crossed-out, previous, or compare-at prices as the selling price.
5. Currency must be a three-letter ISO 4217 code, such as INR or NOK.
6. pack_size is the number of units in the product pack. Use 1 if unspecified.
7. Availability must be unknown if the page does not provide reliable evidence.
8. Never invent missing information. Use null where appropriate.
9. Ignore navigation, recommendations, advertisements and unrelated products.
10. Return JSON only. Do not include Markdown or explanations.
"""


def clean_html(html: str, limit: int = 20000) -> str:
    """Extract useful visible text and structured product metadata."""

    soup = BeautifulSoup(html, "html.parser")
    useful_parts = []

    # Preserve page title.
    if soup.title and soup.title.string:
        useful_parts.append(f"PAGE TITLE: {soup.title.string.strip()}")

    # Preserve useful metadata before removing scripts.
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if key and content:
            useful_parts.append(f"{key}: {content}")

    # Preserve JSON-LD because many product pages store product data here.
    for tag in soup.find_all("script", type="application/ld+json"):
        if tag.string:
            useful_parts.append(f"STRUCTURED PRODUCT DATA: {tag.string}")

    # Remove irrelevant page elements, but retain JSON-LD collected above.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    visible_text = soup.get_text(" ", strip=True)
    visible_text = re.sub(r"\s+", " ", visible_text)

    useful_parts.append(f"VISIBLE PAGE TEXT: {visible_text}")

    return "\n\n".join(useful_parts)[:limit]


def _parse_json(raw: str) -> dict:
    """Parse JSON, including responses accidentally wrapped in Markdown."""

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Empty LLM response")

    text = raw.strip()

    # Remove Markdown code fences if the model adds them.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try extracting the first JSON object from surrounding text.
        decoder = json.JSONDecoder()
        start = text.find("{")

        if start == -1:
            raise ValueError("LLM response does not contain a JSON object")

        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed JSON returned by LLM") from exc

    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object")

    return data


def _valid_price(value, field_name: str):
    """Accept only non-negative integer minor-unit prices or null."""

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or null")

    return value


def _normalise_output(data: dict) -> dict:
    """Validate and normalise the model response."""

    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("name must be a string or null")

    price = _valid_price(data.get("price_cents"), "price_cents")
    compare_at = _valid_price(data.get("compare_at_cents"), "compare_at_cents")

    currency = data.get("currency")
    if currency is not None:
        if not isinstance(currency, str):
            raise ValueError("currency must be a string or null")
        currency = currency.strip().upper()
        if currency and not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter ISO code")

    availability = data.get("availability", "unknown")
    if availability not in {"in_stock", "out_of_stock", "unknown"}:
        raise ValueError("Invalid availability value")

    pack_size = data.get("pack_size", 1)
    if isinstance(pack_size, bool) or not isinstance(pack_size, int) or pack_size < 1:
        raise ValueError("pack_size must be a positive integer")

    return {
        "name": name.strip() if name else "",
        "price_cents": price,
        "currency": currency or "",
        "availability": availability,
        "pack_size": pack_size,
        "compare_at_cents": compare_at,
    }


def extract_with_llm(
    provider: Provider,
    store: str,
    url: str,
    html: str,
    timeout: float = 30.0,
) -> Observation:
    """Call the configured provider and return a validated Observation."""

    user = (
        f"Source URL: {url}\n"
        f"Store: {store}\n\n"
        f"PRODUCT PAGE CONTENT:\n{clean_html(html)}"
    )

    # source_url is required by the provider interface and evaluation harness.
    raw = provider.complete(
        SYSTEM,
        user,
        metadata={"source_url": url, "store": store},
        timeout=timeout,
    )

    # Provider errors and timeouts intentionally propagate to the caller.
    # The evaluation harness is responsible for recording them.
    data = _normalise_output(_parse_json(raw))

    product_id = urlparse(url).path.rstrip("/").split("/")[-1] or url

    return Observation(
        store=store,
        product_id=product_id,
        url=url,
        name=data["name"],
        price_cents=data["price_cents"],
        currency=data["currency"],
        compare_at_cents=data["compare_at_cents"],
        availability=data["availability"],
        pack_size=data["pack_size"],
        source="llm",
    )
 