"""AutoScout24 source.

Reads the `__NEXT_DATA__` JSON blob embedded in the search-results page
(it's a Next.js app) instead of parsing rendered HTML — that blob is the
exact data the page hydrates from, so it's far more stable than scraping
markup. Verified against real responses (2026-08-28): plain `httpx` GETs to
`/lst/tesla/{model-y,model-3}` work fine from this project's dev sandbox, no
bot-detection friction hit yet — unlike Kleinanzeigen/Használtautó.hu, which
still need checking (see README).

`cy` (country) filters cleanly to exactly the requested country — verified
`cy=A` returns only `AT` listings. Hungary (`cy=H`) returned zero results:
AutoScout24 doesn't meaningfully cover HU, which is exactly why
Használtautó.hu is a separate named source in this project rather than
redundant with this one.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

import httpx

from car_tracker.normalize.currency import market_currency
from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.sources.http import build_client

BASE_URL = "https://www.autoscout24.com/lst/tesla"
MAKE_ID = 51520  # Tesla
MODEL_IDS = {"model_y": 75320, "model_3": 74665}
MODEL_SLUGS = {"model_y": "model-y", "model_3": "model-3"}

# AutoScout24's own IVR-style country codes. All of these are eurozone
# markets (see normalize/currency.py) — if a non-eurozone market is ever
# added here, wire it into market_currency() too.
COUNTRY_CODES = {"DE": "D", "AT": "A", "NL": "NL", "BE": "B", "IT": "I", "ES": "E", "FR": "F", "LU": "L"}

PAGE_SIZE = 20
REQUEST_DELAY_SECONDS = 0.5  # be a polite, low-frequency caller across a multi-page paginated scrape

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class AutoScout24Source(Source):
    name = "autoscout24"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or build_client()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "AutoScout24Source":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        listings: list[RawListing] = []
        page = 1
        total_pages = 1
        while page <= total_pages and (max_pages is None or page <= max_pages):
            try:
                page_props = self.fetch_raw_page(model=model, country=country, page=page)
            except Exception as exc:
                # Keep what earlier pages already gave us. A single bad page
                # used to abort the whole combo and discard everything with
                # it: one live run lost twelve good pages of Italian Model Y
                # listings to a 502 on page thirteen. Partial data beats none,
                # and a country vanishing from the dashboard for a day is a
                # much worse outcome than a short tail.
                #
                # PartialResults rather than a plain return, because the
                # caller has to know the tail is missing: the cars on the
                # pages we never fetched are not gone, they are unseen.
                if not listings:
                    raise
                raise PartialResults(listings, f"page {page} failed ({type(exc).__name__}: {exc})") from exc
            total_pages = page_props.get("numberOfPages", 1)
            items = page_props.get("listings", [])
            listings.extend(parse_item(item, model=model) for item in items)
            if not items:
                break
            page += 1
            if page <= total_pages:
                time.sleep(REQUEST_DELAY_SECONDS)
        return listings

    def fetch_raw_page(self, *, model: str, country: str, page: int = 1) -> dict:
        """One page's `pageProps` (includes `listings`, `numberOfPages`, etc.), unparsed."""
        if model not in MODEL_SLUGS:
            raise ValueError(f"unknown model {model!r}, expected one of {sorted(MODEL_SLUGS)}")
        if country not in COUNTRY_CODES:
            raise ValueError(f"unsupported country {country!r} for autoscout24, expected one of {sorted(COUNTRY_CODES)}")

        url = f"{BASE_URL}/{MODEL_SLUGS[model]}"
        params = {
            "atype": "C",
            "ustate": "U",
            "cy": COUNTRY_CODES[country],
            "cat": f"ma{MAKE_ID}mo{MODEL_IDS[model]}",
            "size": PAGE_SIZE,
            "page": page,
        }
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return _extract_page_props(response.text)


def _extract_page_props(html: str) -> dict:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("__NEXT_DATA__ script tag not found — AutoScout24 may have changed its page structure")
    return json.loads(match.group(1))["props"]["pageProps"]


def parse_item(item: dict, *, model: str) -> RawListing:
    details = {d["iconName"]: d["data"] for d in item.get("vehicleDetails", [])}
    first_registration = _parse_month_year(details.get("calendar"))
    country = item.get("location", {}).get("countryCode", "")

    return RawListing(
        source="autoscout24",
        source_listing_id=item["id"],
        model=model,
        country=country,
        url="https://www.autoscout24.com" + item.get("url", ""),
        price_original=float(item.get("price", {}).get("priceRaw") or 0),
        currency_original=market_currency(country),
        mileage_km=_parse_km(details.get("mileage_odometer")),
        model_year=first_registration.year if first_registration else None,
        first_registration=first_registration,
        variant=item.get("vehicle", {}).get("modelVersionInput"),
        title_raw=item.get("vehicle", {}).get("modelVersionInput"),
        photo_urls=item.get("images", []),
        seller_type=_normalize_seller_type(item.get("seller", {}).get("type")),
        location=item.get("location", {}).get("city"),
        power_kw=_parse_power_kw(details.get("speedometer")),
    )


def _parse_km(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_month_year(text: str | None) -> date | None:
    """AutoScout24 first-registration format is "MM/YYYY"."""
    if not text:
        return None
    try:
        month_str, year_str = text.split("/")
        return date(int(year_str), int(month_str), 1)
    except (ValueError, AttributeError):
        return None


def _parse_power_kw(text: str | None) -> int | None:
    """Format is e.g. "220 kW (299 hp)"."""
    if not text:
        return None
    match = re.match(r"\s*(\d+)\s*kW", text)
    return int(match.group(1)) if match else None


def _normalize_seller_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    return {"Dealer": "dealer", "PrivateSeller": "private"}.get(raw, raw.lower())
