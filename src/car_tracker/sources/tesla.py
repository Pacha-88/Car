"""Tesla.com used-inventory source.

Hits Tesla's own inventory JSON endpoint directly rather than parsing HTML —
this endpoint is undocumented but has been used by community inventory
trackers for years with a stable shape, and has no bot-detection friction
from a normal (non-datacenter) IP, unlike AutoScout24/Kleinanzeigen.

`_build_query` (model codes, the query/offset/count envelope,
market/language/super_region/lat/lng/zip/range) and `parse_item` (the field
names read off each result) are both verified against a real response
(2026-08-28, DE, Model Y — `total_matches_found: 101`, 5 results, run from a
normal home connection; this project's dev sandbox is blocked from reaching
tesla.com at all by IP-reputation-based bot defense, see README).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import urlencode

import httpx

from car_tracker.normalize.currency import market_currency
from car_tracker.sources.base import RawListing, Source
from car_tracker.sources.fetch import fetch_json
from car_tracker.sources.http import build_client

INVENTORY_URL = "https://www.tesla.com/inventory/api/v4/inventory-results"

MODEL_CODES = {"model_y": "my", "model_3": "m3"}
PAGE_SIZE = 50

# A representative point per market — Tesla's search wants a lat/lng/zip even
# for a market-wide query. Capital cities + range=0: confirmed this returns
# market-wide (not radius-limited) results for DE.
MARKET_REFERENCE_POINTS: dict[str, dict[str, object]] = {
    "DE": {"lat": 52.5200, "lng": 13.4050, "zip": "10115", "language": "de"},
    "AT": {"lat": 48.2082, "lng": 16.3738, "zip": "1010", "language": "de"},
    "HU": {"lat": 47.4979, "lng": 19.0402, "zip": "1051", "language": "en"},
}


class TeslaSource(Source):
    name = "tesla"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or build_client()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "TeslaSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        listings: list[RawListing] = []
        for page_num, (offset, results, total) in enumerate(self._iter_pages(model, country), start=1):
            listings.extend(parse_item(item, model=model, country=country) for item in results)
            if offset + PAGE_SIZE >= total or (max_pages is not None and page_num >= max_pages):
                break
        return listings

    def fetch_raw_page(self, *, model: str, country: str, offset: int = 0) -> dict:
        """One raw page, unparsed — for inspecting the real response shape.

        Goes through sources/fetch.py rather than this class's httpx client:
        Akamai scores the TLS handshake here, and Python's own is rejected
        outright even from a home connection (see that module).
        """
        payload = _build_query(model, country, offset=offset)
        url = f"{INVENTORY_URL}?{urlencode({'query': json.dumps(payload)})}"
        language = str(MARKET_REFERENCE_POINTS[country]["language"])
        return json.loads(fetch_json(url, accept_language=f"{language},en;q=0.8"))

    def _iter_pages(self, model: str, country: str):
        offset = 0
        while True:
            data = self.fetch_raw_page(model=model, country=country, offset=offset)
            results = data.get("results", [])
            total = data.get("total_matches_found", len(results))
            yield offset, results, total
            offset += PAGE_SIZE
            if offset >= total or not results:
                break


def _build_query(model: str, country: str, *, offset: int = 0) -> dict:
    if model not in MODEL_CODES:
        raise ValueError(f"unknown model {model!r}, expected one of {sorted(MODEL_CODES)}")
    if country not in MARKET_REFERENCE_POINTS:
        raise ValueError(f"no reference point configured for country {country!r}")
    point = MARKET_REFERENCE_POINTS[country]

    return {
        "query": {
            "model": MODEL_CODES[model],
            "condition": "used",
            "options": {},
            "arrangeby": "Price",
            "order": "asc",
            "market": country,
            "language": point["language"],
            "super_region": "europe",
            "lng": point["lng"],
            "lat": point["lat"],
            "zip": point["zip"],
            "range": 0,
        },
        "offset": offset,
        "count": PAGE_SIZE,
        "outsideOffset": 0,
        "outsideSearch": False,
    }


def parse_item(item: dict, *, model: str, country: str) -> RawListing:
    """Field mapping verified against a real response (see module docstring).

    `url` is the one unconfirmed piece — no direct listing-URL field showed
    up in the sample, so this is still a guessed path pattern.
    """
    vin = item.get("VIN", "")
    odometer = item.get("Odometer")
    unit = item.get("OdometerTypeShort") or item.get("OdometerType") or "km"
    if odometer is not None and str(unit).lower().startswith("mi"):
        odometer = round(odometer * 1.60934)

    paint = item.get("PAINT") or []
    photos = [p["imageUrl"] for p in item.get("VehiclePhotos", []) if p.get("imageUrl")]

    return RawListing(
        source="tesla",
        source_listing_id=vin,
        model=model,
        country=country,
        url=f"https://www.tesla.com/{country.lower()}/inventory/used/{MODEL_CODES[model]}/{vin}",
        price_original=float(item.get("Price", 0)),
        currency_original=item.get("CurrencyCode") or market_currency(country),
        mileage_km=odometer,
        model_year=item.get("Year"),
        first_registration=_parse_iso_date(item.get("FirstRegistrationDate")),
        variant=item.get("TrimVariantCode") or item.get("TrimName"),
        title_raw=None,  # Tesla listings don't have a free-text title to re-parse later, unlike marketplace ads
        photo_urls=photos,
        seller_type="tesla",
        location=item.get("City"),
        power_kw=(item.get("EmissionsData") or {}).get("power"),
        color=paint[0].lower() if paint else None,
    )


def _parse_iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
