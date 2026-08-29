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
import time
from datetime import date, datetime
from urllib.parse import urlencode

import httpx

from car_tracker.normalize.color import normalize_color
from car_tracker.normalize.currency import market_currency
from car_tracker.normalize.title import model_display_name
from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.sources.fetch import FetchError, fetch_json
from car_tracker.sources.http import build_client

INVENTORY_URL = "https://www.tesla.com/inventory/api/v4/inventory-results"

MODEL_CODES = {"model_y": "my", "model_3": "m3"}
PAGE_SIZE = 50

# This source used to fire every page of every market back to back with no
# pacing at all - six model/market combos in a burst - and the first live
# run answered with HTTP 429 on all of them. Tesla's inventory API is not
# refusing this project, it is rate-limiting a burst, so the fix is to stop
# bursting rather than to try harder.
REQUEST_DELAY_SECONDS = 3.0

# A representative point per market — Tesla's search wants a lat/lng/zip even
# for a market-wide query. Capital cities + range=0: confirmed this returns
# market-wide (not radius-limited) results for DE.
MARKET_REFERENCE_POINTS: dict[str, dict[str, object]] = {
    "DE": {"lat": 52.5200, "lng": 13.4050, "zip": "10115", "language": "de"},
    "AT": {"lat": 48.2082, "lng": 16.3738, "zip": "1010", "language": "de"},
    "HU": {"lat": 47.4979, "lng": 19.0402, "zip": "1051", "language": "en"},
}

# tesla.com site locale per market - the order deep link below needs it.
MARKET_LOCALES = {"DE": "de_DE", "AT": "de_AT", "HU": "hu_HU"}


def listing_url(model: str, country: str, vin: str) -> str:
    """The order page for one used car.

    The first guess here - /{cc}/inventory/used/{model}/{vin} - was marked
    unverified in this file and turned out to 404 on every listing (the
    inventory path is the *search* page, which takes no VIN). The pattern
    community inventory trackers have deep-linked for years is the order
    page: tesla.com/{locale}/{model}/order/{VIN}. Unverifiable from this
    sandbox (tesla.com refuses datacenter traffic outright), so the proof
    is a click after the next scrape-local run.
    """
    locale = MARKET_LOCALES.get(country, "en_US")
    return f"https://www.tesla.com/{locale}/{MODEL_CODES[model]}/order/{vin}?titleStatus=used"


def stock_photo(item: dict, *, model: str) -> list[str]:
    """A configurator render for a car with no inspection photos.

    Many used-inventory entries carry an empty VehiclePhotos (no inspection
    shoot yet) - which left every one of them as a bare placeholder card.
    Tesla's own site shows those cars as a configurator render built from
    the option codes, and the compositor endpoint that draws it is public
    and hotlinkable; every community inventory tracker uses it. No codes,
    no render - an empty list keeps the placeholder.
    """
    # The pasted sample this module was built from did not include the
    # option-code field, and tesla.com is unreachable from this sandbox to
    # check the spelling - so accept every shape the API has been seen to
    # use over the years rather than betting on one: a comma string, a
    # plain list, or OptionCodeData's list of {"code": ...} dicts.
    raw_codes = (
        item.get("OptionCodeList")
        or item.get("OptionCodeListDisplayOnly")
        or item.get("OptionCodeData")
        or []
    )
    if isinstance(raw_codes, str):
        codes = raw_codes.split(",")
    else:
        codes = [c.get("code", "") if isinstance(c, dict) else str(c) for c in raw_codes]
    cleaned = [c.strip().lstrip("$") for c in codes if c and c.strip()]
    if not cleaned:
        return []
    options = ",".join(f"${c}" for c in cleaned)
    return [
        "https://static-assets.tesla.com/configurator/compositor"
        f"?context=design_studio_2&options={options}&view=STUD_3QTR&model={MODEL_CODES[model]}&size=1441&bkba_opt=1"
    ]


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
        pages_done = 0
        photoless_sample: dict | None = None
        unparsable: tuple[int, str] = (0, "")
        try:
            for page_num, (offset, results, total) in enumerate(self._iter_pages(model, country), start=1):
                for item in results:
                    try:
                        raw = parse_item(item, model=model, country=country)
                    except Exception as exc:  # noqa: BLE001 - see below
                        # One odd car must not cost the whole market. A
                        # single AT item whose EmissionsData was a string
                        # took down all of tesla/model_y/AT - 0 listings
                        # kept from a market that had answered fine.
                        unparsable = (unparsable[0] + 1, f"{type(exc).__name__}: {exc}")
                        continue
                    if not raw.photo_urls and photoless_sample is None:
                        photoless_sample = item
                    listings.append(raw)
                pages_done = page_num
                if offset + PAGE_SIZE >= total or (max_pages is not None and page_num >= max_pages):
                    break
        except FetchError as exc:
            # 412 at BOTH stages, on the very first page, is not a wall: HU
            # answered that way every time, twice per run, while DE and AT
            # answered normally from the same address in the same minute.
            # Tesla's inventory API simply will not serve that market.
            #
            # Treated as an empty market rather than a failure, and
            # deliberately not as a partial either: both of those mark the
            # source incomplete, and a market that refuses on every single
            # run would then block retirement for ALL of Tesla forever -
            # so sold cars in Germany would never leave the dashboard. The
            # protection against a real API-wide outage is the retirement
            # share cap in cli.py, which is exactly the case it exists for.
            if not listings and set(exc.statuses) == {412}:
                print(
                    f"    tesla/{model}/{country}: the inventory API refuses this market "
                    f"(HTTP 412 at both stages) - treating it as empty, not as a block"
                )
                return []
            raise
        except Exception as exc:
            # A rate limit or a wall part-way through a market is the common
            # case here (this API answered a whole burst with 429 once), and
            # the pages already in hand are current prices. Keep them - but
            # as PartialResults, so the caller knows the rest of the market
            # was never looked at and doesn't read "unseen" as "sold".
            if not listings:
                raise
            raise PartialResults(
                listings, f"page {pages_done + 1} failed ({type(exc).__name__}: {exc})"
            ) from exc
        if unparsable[0]:
            print(
                f"    tesla/{model}/{country}: skipped {unparsable[0]} item(s) this parser could not"
                f" read ({unparsable[1]}) - kept the other {len(listings)}"
            )
        self._report_photoless(listings, photoless_sample, model=model, country=country)
        return listings

    @staticmethod
    def _report_photoless(listings: list[RawListing], sample: dict | None, *, model: str, country: str) -> None:
        """Say which fields a photo-less car actually carries.

        A card with no photo means the item had neither inspection photos
        nor any option-code field this module recognises - and since the
        real response shape cannot be inspected from the dev sandbox
        (tesla.com refuses datacenter traffic), the person running
        scrape-local at home is the only one who ever sees a real item.
        One line in their log turns "still no photos" into the exact field
        list needed to fix the mapping.
        """
        photoless = sum(1 for raw in listings if not raw.photo_urls)
        if not photoless or sample is None:
            return
        print(
            f"    tesla/{model}/{country}: {photoless} of {len(listings)} cars have no photos and no"
            f" recognised option codes - fields on one such car: {sorted(sample.keys())}"
        )

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
        first = True
        while True:
            if not first:
                time.sleep(REQUEST_DELAY_SECONDS)
            first = False
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


def _compose_title(item: dict, *, model: str) -> str:
    """A readable title for a Tesla listing.

    Unlike a marketplace ad, Tesla's inventory has no free-text headline -
    this source used to store None, so every Tesla card in the dashboard
    read "Untitled" while its neighbours showed real ad titles. Tesla does
    publish the structured pieces a headline is made of, so compose one:
    "Model Y Long Range AWD · 2022 · Black".
    """
    parts: list[str] = [model_display_name(model)]

    trim = item.get("TrimName") or item.get("TrimVariantCode")
    if trim:
        parts.append(str(trim))

    year = item.get("Year")
    if year:
        parts.append(str(year))

    first_paint = _first_paint(item)
    if first_paint:
        # "MIDNIGHT_SILVER" -> "Midnight Silver"
        parts.append(first_paint.replace("_", " ").title())

    return " · ".join(parts)


def _first_paint(item: dict) -> str | None:
    """Tesla's PAINT is a list of codes - except when it is a bare string.

    A live AT response crashed the whole market with "'str' object has no
    attribute 'get'"; the same per-market shape drift that stock_photo
    already guards for in the option-code field reaches these three, so
    they guard for it the same way rather than trusting one shape.
    """
    paint = item.get("PAINT")
    if isinstance(paint, str):
        return paint or None
    if isinstance(paint, (list, tuple)) and paint:
        first = paint[0]
        return str(first) if first else None
    return None


def _photo_urls(item: dict) -> list[str]:
    """VehiclePhotos entries are {"imageUrl": ...} dicts - or plain URLs."""
    photos = item.get("VehiclePhotos")
    if not isinstance(photos, (list, tuple)):
        return []
    urls: list[str] = []
    for entry in photos:
        if isinstance(entry, dict):
            url = entry.get("imageUrl")
        elif isinstance(entry, str):
            url = entry
        else:
            url = None
        if url:
            urls.append(str(url))
    return urls


def _power_kw(item: dict) -> int | None:
    """EmissionsData is an object on some markets and a string on others."""
    data = item.get("EmissionsData")
    power = data.get("power") if isinstance(data, dict) else None
    if power is None:
        return None
    try:
        return int(float(power))
    except (TypeError, ValueError):
        return None


def parse_item(item: dict, *, model: str, country: str) -> RawListing:
    """Field mapping verified against a real response (see module docstring)."""
    vin = item.get("VIN", "")
    odometer = item.get("Odometer")
    unit = item.get("OdometerTypeShort") or item.get("OdometerType") or "km"
    if odometer is not None and str(unit).lower().startswith("mi"):
        odometer = round(odometer * 1.60934)

    photos = _photo_urls(item) or stock_photo(item, model=model)

    return RawListing(
        source="tesla",
        source_listing_id=vin,
        model=model,
        country=country,
        url=listing_url(model, country, vin),
        price_original=float(item.get("Price", 0)),
        currency_original=item.get("CurrencyCode") or market_currency(country),
        mileage_km=odometer,
        model_year=item.get("Year"),
        first_registration=_parse_iso_date(item.get("FirstRegistrationDate")),
        variant=item.get("TrimVariantCode") or item.get("TrimName"),
        title_raw=_compose_title(item, model=model),
        photo_urls=photos,
        seller_type="tesla",
        location=item.get("City"),
        power_kw=_power_kw(item),
        color=normalize_color(_first_paint(item)),
    )


def _parse_iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
