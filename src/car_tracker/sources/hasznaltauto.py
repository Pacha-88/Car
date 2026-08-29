"""Használtautó.hu source. HU only.

Server-rendered HTML (no JSON blob, like Kleinanzeigen rather than
AutoScout24). Listing rows are deeply nested `<div>`s with no unique
closing marker to regex against, unlike Kleinanzeigen's `<article>` cards
— so instead of matching a start/end pair, the page is split right before
each occurrence of the row's opening marker (`_LISTING_START`), and each
resulting chunk (which runs into the *next* listing's opening tag, or the
page footer for the last one) is searched for this listing's fields. That
works because every field this module reads appears once, near the top of
its own listing's chunk, well before the next chunk boundary — but it does
mean the last chunk on a page contains a lot of trailing footer/script
HTML along for the ride.

This sandbox itself cannot reach hasznaltauto.hu (Cloudflare Bot Management
403s it — see README); the shapes below, and the `/szemelyauto/tesla/{slug}`
+ `/page{N}` URL pattern (confirmed from the page's own `rel="next"`/
`rel="last"` links, not guessed), come from a real response the project
owner fetched from a normal home connection and pasted in
(2026-08-28, Model Y). Model 3's slug is inferred by the same naming
convention, not directly confirmed.

Known gaps, not solved here:
- No used-vs-new filter is applied. The page title itself says "Eladó új
  és használt" ("new and used for sale") — results mix both, and the
  search form has a `hasznalt_jarmu` (used) checkbox, but it's submitted
  through a different endpoint (a POST form) than the clean URL this
  module uses, and guessing the right query-param equivalent without
  verification felt worse than leaving it alone.
- No per-listing location: unlike the other three sources, search results
  here don't surface a city/place name, only a "distance from you" widget
  that needs a postcode this fetch doesn't supply.
"""

from __future__ import annotations

import re
import time
from datetime import date

import httpx

from car_tracker.normalize.currency import market_currency
from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.sources.fetch import fetch_html
from car_tracker.sources.http import build_client

BASE_URL = "https://www.hasznaltauto.hu/szemelyauto/tesla"
MODEL_SLUGS = {"model_y": "model_y", "model_3": "model_3"}  # model_3 unconfirmed

REQUEST_DELAY_SECONDS = 2.0  # same conservative starting point as kleinanzeigen.py

_LISTING_START = '<div class="row talalati-sor'
_HIRKOD_RE = re.compile(r'data-hirkod="(\d+)"')
_TITLE_URL_RE = re.compile(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>\s*</h3>')
_REG_DATE_RE = re.compile(r'<span class="info[^"]*">\s*(\d{4})/(\d{1,2}),\s*</span>')
_POWER_RE = re.compile(r'<span class="info[^"]*">\s*(\d+)\s*kW,\s*</span>')
_MILEAGE_RE = re.compile(r"<abbr[^>]*>([\d\s]+)\s*km</abbr>")
_PRICE_RE = re.compile(r"pricefield-primary(?:-highlighted)?\">\s*([\d\s]+)\s*Ft\s*</div>")
_DESCRIPTION_RE = re.compile(r'talalati-sor__leiras"[^>]*>(.*?)</div>', re.S)
_SELLER_RE = re.compile(r'trader-name">\s*([^<]+?)\s*</span>')
_IMAGE_RE = re.compile(r'<img class="img-responsive" src="([^"]+)"')


class HasznaltautoSource(Source):
    name = "hasznaltauto"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        # A Hungarian site: a real browser opening it would usually ask for Hungarian first.
        self.client = client or build_client(accept_language="hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "HasznaltautoSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        if country != "HU":
            raise ValueError(f"hasznaltauto only covers HU, got {country!r}")

        listings: list[RawListing] = []
        page = 1
        while max_pages is None or page <= max_pages:
            try:
                html = self.fetch_raw_page(model=model, page=page)
            except Exception as exc:
                # Same rule as the other sources: pages already fetched are
                # real data and must not be thrown away with the failure.
                # It matters most here - every page goes through Cloudflare
                # (see sources/fetch.py), so a challenge appearing at page
                # three, after one and two were served fine, is the normal
                # way this source fails rather than an unlucky one.
                if not listings:
                    raise
                raise PartialResults(listings, f"page {page} failed ({type(exc).__name__}: {exc})") from exc
            chunks = _split_listings(html)
            if not chunks:
                break
            listings.extend(parsed for c in chunks if (parsed := parse_item(c, model=model)) is not None)
            page += 1
            if max_pages is None or page <= max_pages:
                time.sleep(REQUEST_DELAY_SECONDS)
        return listings

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        """One page's raw HTML — for inspecting the real response shape.

        Goes through sources/fetch.py rather than this class's httpx client:
        Cloudflare scores the TLS handshake here, and Python's own is
        rejected outright even from a home connection (see that module).
        """
        if model not in MODEL_SLUGS:
            raise ValueError(f"unknown model {model!r}, expected one of {sorted(MODEL_SLUGS)}")
        slug = MODEL_SLUGS[model]
        url = f"{BASE_URL}/{slug}" if page == 1 else f"{BASE_URL}/{slug}/page{page}"
        return fetch_html(url, accept_language="hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7")


def _split_listings(html: str) -> list[str]:
    parts = html.split(_LISTING_START)
    return [_LISTING_START + part for part in parts[1:]]


def parse_item(chunk: str, *, model: str) -> RawListing | None:
    hirkod = _HIRKOD_RE.search(chunk)
    title_url = _TITLE_URL_RE.search(chunk)
    price_match = _PRICE_RE.search(chunk)
    if not hirkod or not title_url or not price_match:
        return None

    price = _parse_number(price_match.group(1))
    if price is None:
        return None

    reg_match = _REG_DATE_RE.search(chunk)
    first_registration = date(int(reg_match.group(1)), int(reg_match.group(2)), 1) if reg_match else None
    power_match = _POWER_RE.search(chunk)
    mileage_match = _MILEAGE_RE.search(chunk)
    seller_match = _SELLER_RE.search(chunk)
    image_match = _IMAGE_RE.search(chunk)
    title_text = title_url.group(2).strip()

    return RawListing(
        source="hasznaltauto",
        source_listing_id=hirkod.group(1),
        model=model,
        country="HU",
        url="https://www.hasznaltauto.hu" + title_url.group(1),
        price_original=float(price),
        currency_original=market_currency("HU"),
        mileage_km=_parse_number(mileage_match.group(1)) if mileage_match else None,
        model_year=first_registration.year if first_registration else None,
        first_registration=first_registration,
        # No structured trim field, same situation as Kleinanzeigen - the
        # title feeds the shared central normalize_variant() call.
        variant=title_text,
        title_raw=title_text,
        photo_urls=[image_match.group(1)] if image_match else [],
        seller_type=_normalize_seller(seller_match.group(1)) if seller_match else None,
        location=None,  # not present in search-result markup, see module docstring
        power_kw=int(power_match.group(1)) if power_match else None,
    )


def _parse_number(text: str) -> int | None:
    digits = re.sub(r"\s+", "", text)
    return int(digits) if digits.isdigit() else None


def _normalize_seller(text: str) -> str:
    return "dealer" if text.startswith("Kereskedés") else "private"
