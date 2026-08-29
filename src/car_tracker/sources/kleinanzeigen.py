"""Kleinanzeigen (kleinanzeigen.de) source. DE only.

Server-rendered HTML, not a JSON blob like AutoScout24 — parses the
`.aditem` search-result cards directly with regex. More fragile than
AutoScout24's approach (a markup redesign breaks this silently; a
data-shape change there is less likely to), but the shapes below and the
`/s-autos/{slug}/k0c216` URL (plus the `seite:N` pagination pattern, read
off the page's own pagination links) are verified against a real response
(2026-08-28, DE, Model Y search).

CAVEAT: shortly after that, this project's dev sandbox got a temporary
"IP-Bereich gesperrt" (IP-range blocked) page from Kleinanzeigen's own
anti-abuse system, after well under a dozen requests in a couple of
minutes — see README. The parser here is verified against a saved real
response (tests/fixtures/kleinanzeigen_search_sample.html), not a fresh
live fetch after that point. Whatever runs this for real needs to be
gentler than this sandbox's exploratory probing was — hence the longer
REQUEST_DELAY_SECONDS than autoscout24.py uses, as a starting point to
tune, not a guarantee.

Kleinanzeigen mixes "for sale" and "wanted" ("Gesuch") ads in search
results — filtered out here by the literal "Gesuch" tag Kleinanzeigen
itself puts on those, not by any heuristic on price or title text. A
listing with no fixed price ("VB" with no number at all) is dropped too —
there's nothing to track without a starting price.
"""

from __future__ import annotations

import re
import time
from datetime import date

import httpx

from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.sources.http import build_client

BASE_URL = "https://www.kleinanzeigen.de/s-autos"
MODEL_SLUGS = {"model_y": "tesla-model-y", "model_3": "tesla-model-3"}
CATEGORY = "k0c216"  # "Autos" (cars)

REQUEST_DELAY_SECONDS = 2.0

_ARTICLE_RE = re.compile(r'<article class="aditem"[^>]*>.*?</article>', re.S)
_ADID_RE = re.compile(r'data-adid="(\d+)"')
_HREF_RE = re.compile(r'data-href="([^"]+)"')
_TITLE_RE = re.compile(r'<a class="ellipsis"[^>]*>([^<]+)</a>')
_PRICE_BLOCK_RE = re.compile(r'price-shipping--price">\s*([^<]+?)\s*<')
_TAG_RE = re.compile(r'<span class="simpletag">\s*([^<]+?)\s*</span>')
_LOCATION_RE = re.compile(r'icon-pin-gray"[^>]*></i>\s*([^<\n]+)')
_IMAGE_RE = re.compile(r'"contentUrl":"([^"]+)"')

_PRICE_NUMBER_RE = re.compile(r"([\d.]+)\s*€")
_MILEAGE_TAG_RE = re.compile(r"^([\d.]+)\s*km$")
_FIRST_REG_TAG_RE = re.compile(r"^EZ\s+(\d{2})/(\d{4})$")
_LEADING_ZIP_RE = re.compile(r"^\d{4,5}\s+")


class KleinanzeigenSource(Source):
    name = "kleinanzeigen"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or build_client(accept_language="de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "KleinanzeigenSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        if country != "DE":
            raise ValueError(f"kleinanzeigen only covers DE, got {country!r}")

        listings: list[RawListing] = []
        page = 1
        while max_pages is None or page <= max_pages:
            try:
                html = self.fetch_raw_page(model=model, page=page)
            except Exception as exc:
                # Same reasoning as autoscout24: one live run threw away a
                # whole page of good Model Y ads because page 2 answered 403.
                if not listings:
                    raise
                raise PartialResults(listings, f"page {page} failed ({type(exc).__name__}: {exc})") from exc
            articles = _ARTICLE_RE.findall(html)
            if not articles:
                # Could be the end of the results, or a throttle page that
                # simply has no ads on it - HTTP 200 either way, and nothing
                # in the response tells them apart. Calling it partial would
                # be wrong on every healthy run (the last page is always
                # empty, that is how the loop ends) and would mean this
                # source could never retire anything. So stop here, and let
                # the retirement cap in cli.py catch the case where this was
                # a throttle: a run that suddenly "sees" a fraction of the
                # ads is refused there, whatever the cause.
                break
            listings.extend(parsed for a in articles if (parsed := parse_item(a, model=model)) is not None)
            page += 1
            if max_pages is None or page <= max_pages:
                time.sleep(REQUEST_DELAY_SECONDS)
        return listings

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        """One page's raw HTML — for inspecting the real response shape."""
        if model not in MODEL_SLUGS:
            raise ValueError(f"unknown model {model!r}, expected one of {sorted(MODEL_SLUGS)}")
        slug = MODEL_SLUGS[model]
        url = f"{BASE_URL}/{slug}/{CATEGORY}" if page == 1 else f"{BASE_URL}/seite:{page}/{slug}/{CATEGORY}"
        response = self.client.get(url)
        response.raise_for_status()
        return response.text


def parse_item(article_html: str, *, model: str) -> RawListing | None:
    tags = [t.strip() for t in _TAG_RE.findall(article_html)]
    if "Gesuch" in tags:
        return None

    price_block = _PRICE_BLOCK_RE.search(article_html)
    price = _parse_price(price_block.group(1)) if price_block else None
    if price is None:
        return None

    adid = _ADID_RE.search(article_html)
    href = _HREF_RE.search(article_html)
    title = _TITLE_RE.search(article_html)
    location = _LOCATION_RE.search(article_html)
    image = _IMAGE_RE.search(article_html)
    first_registration = _parse_first_registration(tags)
    title_text = title.group(1).strip() if title else None

    return RawListing(
        source="kleinanzeigen",
        source_listing_id=adid.group(1) if adid else "",
        model=model,
        country="DE",
        url=("https://www.kleinanzeigen.de" + href.group(1)) if href else "",
        price_original=price,
        currency_original="EUR",
        mileage_km=_parse_mileage(tags),
        model_year=first_registration.year if first_registration else None,
        first_registration=first_registration,
        # No structured trim field here (unlike AutoScout24's modelVersionInput)
        # - the free-text title is the only signal, fed through the same
        # central normalize_variant() call as every other source.
        variant=title_text,
        title_raw=title_text,
        photo_urls=[image.group(1)] if image else [],
        seller_type="dealer" if "badge-hint-pro-small-srp" in article_html else "private",
        location=_LEADING_ZIP_RE.sub("", location.group(1).strip()) if location else None,
    )


def _parse_price(text: str) -> float | None:
    match = _PRICE_NUMBER_RE.search(text)
    if not match:
        return None
    digits = match.group(1).replace(".", "")
    return float(digits) if digits else None


def _parse_mileage(tags: list[str]) -> int | None:
    for tag in tags:
        match = _MILEAGE_TAG_RE.match(tag)
        if match:
            return int(match.group(1).replace(".", ""))
    return None


def _parse_first_registration(tags: list[str]) -> date | None:
    for tag in tags:
        match = _FIRST_REG_TAG_RE.match(tag)
        if match:
            return date(int(match.group(2)), int(match.group(1)), 1)
    return None
