"""Extractor agent: one adapter per storefront turns a fetched page into an Observation.

Adapters receive the raw HTML (already fetched by the Client) and the URL. They must not do
their own networking except through the Client they are given, so throttling and cookies
stay in one place.

Adapters are registered by name; `stores.yaml` maps each store to an adapter.
"""
# The Necessary Imports 
from __future__ import annotations

import json
import re
from typing import Callable, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Observation
from .normalizer import parse_money, unit_price

ADAPTERS: dict[str, Callable[[Client, str, str, str], Observation]] = {}


def adapter(name: str):
    def deco(fn):
        ADAPTERS[name] = fn
        return fn
    return deco


def _pid_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


# --------------------------------------------------------------------------- level 1
@adapter("corner")
def extract_corner(client: Client, store: str, url: str, html: str) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    ld = soup.find("script", type="application/ld+json")
    data = json.loads(ld.string) if ld and ld.string else {}
    offer = data.get("offers", {})
    price_cents, currency = parse_money(str(offer.get("price", "")), offer.get("priceCurrency"))
    was = soup.find("s")
    compare, _ = parse_money(was.get_text(), currency) if was else (None, None)
    return Observation(
        store=store, product_id=data.get("sku") or _pid_from_url(url), url=url,
        name=data.get("name") or soup.h1.get_text(strip=True),
        price_cents=price_cents, currency=currency or "USD", compare_at_cents=compare,
        availability="in_stock" if "InStock" in str(offer.get("availability", "")) else "out_of_stock",
    )


# --------------------------------------------------------------------------- level 2
# @adapter("maple")
# def extract_maple(client: Client, store: str, url: str, html: str) -> Observation:
#     soup = BeautifulSoup(html, "html.parser")
#     name = soup.select_one(".product__title").get_text(strip=True)
#     price_el = soup.select_one(".price .price")  # first price element in the price block
#     price_cents, currency = parse_money(price_el.get_text(" ", strip=True), "EUR")
#     compare_el = soup.select_one(".price--compare")
#     compare, _ = parse_money(compare_el.get_text(" ", strip=True), currency) if compare_el else (None, None)
#     avail = "out_of_stock" if "Sold out" in soup.get_text() else "in_stock"
#     return Observation(
#         store=store, product_id=_pid_from_url(url), url=url, name=name,
#         price_cents=price_cents, currency=currency or "EUR", compare_at_cents=compare, availability=avail,
#     )


# --------- My Revised Extract Maple Function ----------------- 

# Maple prints each variant as an <option>, e.g. "Navy / S — 98,72 €". The text before the
# dash is the variant label; the text after it is the price. The option's `value` is a
# stable variant id, so each variant gets its own price history: "<product>#<variant id>".
_OPTION_PRICE = re.compile(r"[—–-]\s*(\d[\d.,\s\u00a0\u202f]*\s*(?:€|EUR)?)\s*$")


@adapter("maple")
def extract_maple(client: Client, store: str, url: str, html: str) -> list[Observation]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one(".product") or soup  # stay inside the main product block
    title_el = main.select_one(".product__title")
    name = title_el.get_text(strip=True) if title_el else ""
    pid = _pid_from_url(url)

    # Old (crossed-out) price. Only the selected variant gets it, because the page
    # shows a single compare price.
    compare_el = main.select_one(".price--compare")
    compare, _ = parse_money(compare_el.get_text(" ", strip=True), "EUR") if compare_el else (None, None)

    # The page prints one stock line for the whole product.
    note_el = main.select_one(".muted")
    note_text = note_el.get_text(" ", strip=True).lower() if note_el else ""
    page_sold_out = "sold out" in note_text or "out of stock" in note_text

    results: list[Observation] = []
    for opt in main.select("select[name=variant] option"):
        text = opt.get_text(" ", strip=True)
        m = _OPTION_PRICE.search(text)
        if not m:
            continue  # a placeholder option such as "Choose a variant"
        label = text[:m.start()].strip()
        price_cents, currency = parse_money(m.group(1), "EUR")
        variant_id = opt.get("value") or label
        sold_out = page_sold_out or opt.has_attr("disabled")
        results.append(Observation(
            store=store, product_id=f"{pid}#{variant_id}", url=url,
            name=f"{name} ({label})" if label else name,
            price_cents=price_cents, currency=currency or "EUR",
            compare_at_cents=compare if opt.has_attr("selected") else None,
            availability="out_of_stock" if sold_out else "in_stock",
        ))

    if results:
        return results

    # No dropdown: a single-variant product. Read the sale price, never the compare price.
    sale_el = main.select_one(".price--sale") or main.select_one(".price .price:not(.price--compare)")
    price_cents, currency = parse_money(sale_el.get_text(" ", strip=True), "EUR") if sale_el else (None, "EUR")
    return [Observation(
        store=store, product_id=pid, url=url, name=name,
        price_cents=price_cents, currency=currency or "EUR", compare_at_cents=compare,
        availability="out_of_stock" if page_sold_out else "in_stock",
        notes=[] if price_cents is not None else ["no price found"],
    )]

# --------------------------------------------------------------------------- level 3
# Class names used by Zon's product page template.
ZON_CLASSES = {"price": "a-1c3f89", "whole": "a-2b2181", "frac": "a-4e2865", "title": "a-affa10", "avail": "a-78b7d1", "unit": "a-702121"}


@adapter("zon")
def extract_zon(client: Client, store: str, url: str, html: str) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    if "Are you a human" in html:
        return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                           currency="USD", notes=["robot check page"])
    title = soup.find(class_=ZON_CLASSES["title"])
    name = title.get_text(strip=True) if title else ""
    m = re.search(r"Pack of (\d+)", name)
    pack = int(m.group(1)) if m else 1
    box = soup.find(class_=ZON_CLASSES["price"])
    price_cents: Optional[int] = None
    if box:
        whole = box.find(class_=ZON_CLASSES["whole"])
        frac = box.find(class_=ZON_CLASSES["frac"])
        if whole and frac:
            price_cents, _ = parse_money(f"${whole.get_text()}.{frac.get_text()}", "USD")
    avail_el = soup.find(class_=ZON_CLASSES["avail"])
    avail = "out_of_stock" if avail_el and "out of stock" in avail_el.get_text().lower() else "in_stock"
    return Observation(
        store=store, product_id=_pid_from_url(url), url=url, name=re.sub(r"\s*\(Pack of \d+\)", "", name),
        price_cents=price_cents, currency="USD", availability=avail, pack_size=pack,
        unit_price_cents=unit_price(price_cents, pack),
        notes=[] if price_cents is not None else ["no price found"],
    )


# --------------------------------------------------------------------------- levels 4-5
@adapter("shield")
def extract_shield(client: Client, store: str, url: str, html: str) -> Observation:
    # TODO: not implemented yet.
    return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                       currency="GBP", notes=["shield adapter not implemented"])


@adapter("flux")
def extract_flux(client: Client, store: str, url: str, html: str) -> Observation:
    # TODO: not implemented yet.
    return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                       currency="USD", notes=["flux adapter not implemented"])


def extract(client: Client, store: str, adapter_name: str, url: str, html: str) -> Observation:
    fn = ADAPTERS.get(adapter_name)
    if fn is None:
        raise KeyError(f"no adapter named {adapter_name!r}")
    return fn(client, store, url, html)
