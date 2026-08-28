"""Tesla.com used-inventory source.

Hits Tesla's own inventory JSON endpoint directly rather than parsing HTML —
this endpoint is undocumented but has been used by community inventory
trackers for years with a stable shape, and typically has no bot-detection
friction (unlike AutoScout24/Kleinanzeigen).

CAVEAT: this sandbox currently cannot reach tesla.com (organization network
policy — see project README), so nothing here has been checked against a
live response yet. `_build_query` (the request shape: model codes, the
query/offset/count envelope, market/language/super_region/lat/lng/zip/range)
is the well-established part. `parse_item` — the field names read off each
result — is a best-effort guess and is exactly what to check first, e.g. via:

    python -m car_tracker.cli tesla-raw-sample --model model_y --country DE

which dumps one raw page to JSON so the field mapping below can be corrected
against real data instead of guesswork.
"""

from __future__ import annotations

import json
from datetime import date

import httpx

from car_tracker.sources.base import RawListing, Source

INVENTORY_URL = "https://www.tesla.com/inventory/api/v4/inventory-results"

MODEL_CODES = {"model_y": "my", "model_3": "m3"}
PAGE_SIZE = 50

# A representative point per market — Tesla's search wants a lat/lng/zip even
# for a market-wide query. Capital cities + range=0 is the common pattern in
# public trackers for "whole market", but that needs confirming live.
MARKET_REFERENCE_POINTS: dict[str, dict[str, object]] = {
    "DE": {"lat": 52.5200, "lng": 13.4050, "zip": "10115", "language": "de"},
    "AT": {"lat": 48.2082, "lng": 16.3738, "zip": "1010", "language": "de"},
    "HU": {"lat": 47.4979, "lng": 19.0402, "zip": "1051", "language": "en"},
}


class TeslaSource(Source):
    name = "tesla"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"})

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "TeslaSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str) -> list[RawListing]:
        listings: list[RawListing] = []
        for offset, results, total in self._iter_pages(model, country):
            listings.extend(parse_item(item, model=model, country=country) for item in results)
            if offset + PAGE_SIZE >= total:
                break
        return listings

    def fetch_raw_page(self, *, model: str, country: str, offset: int = 0) -> dict:
        """One raw page, unparsed — for inspecting the real response shape."""
        payload = _build_query(model, country, offset=offset)
        response = self.client.get(INVENTORY_URL, params={"query": json.dumps(payload)})
        response.raise_for_status()
        return response.json()

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
    """Best-effort field mapping — NOT yet checked against a live response.

    Field names are the ones commonly reported for this endpoint (Price,
    VIN, Year, Odometer/OdometerTypeUnit, TrimName); Tesla has changed this
    shape before without notice, so verify with fetch_raw_page() before
    trusting any of this. Photo URLs are deliberately left empty: they're
    normally derived from a separate compositor/asset service keyed by
    option codes rather than present as plain URLs, and that derivation
    isn't implemented yet.
    """
    vin = item.get("VIN", "")
    odometer = item.get("Odometer")
    if odometer is not None and str(item.get("OdometerTypeUnit", "km")).lower().startswith("mi"):
        odometer = round(odometer * 1.60934)

    return RawListing(
        source="tesla",
        source_listing_id=vin,
        model=model,
        country=country,
        url=f"https://www.tesla.com/{country.lower()}/inventory/used/{MODEL_CODES[model]}/{vin}",
        price_original=float(item.get("Price", 0)),
        currency_original=_market_currency(country),
        mileage_km=odometer,
        model_year=item.get("Year"),
        first_registration=None,
        variant=item.get("TrimName"),
        title_raw=None,  # Tesla listings don't have a free-text title to re-parse later, unlike marketplace ads
        photo_urls=[],
        seller_type="tesla",
        location=item.get("VehicleLocation") or item.get("City"),
    )


def _market_currency(country: str) -> str:
    return {"DE": "EUR", "AT": "EUR", "HU": "HUF"}.get(country, "EUR")
