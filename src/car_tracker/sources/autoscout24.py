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

from car_tracker.normalize.color import color_from_autoscout24_url
from car_tracker.normalize.currency import market_currency
from car_tracker.normalize.title import model_display_name
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

# A real offer path is `/offers/{make}-{model}-{version}-{fuel}-{colour}-cat_ma…`
# and a bare id is a 36-character uuid; both clear this comfortably. One
# live card came back with `"url": "/offers/x"`, which is a placeholder and
# a 404 for anyone who clicks the card.
MIN_OFFER_SLUG_LENGTH = 12

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
        unreadable: tuple[int, str] = (0, "")
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
            items = page_props.get("listings") or []
            kept = 0
            for item in items:
                try:
                    listings.append(parse_item(item, model=model))
                    kept += 1
                except Exception as exc:  # noqa: BLE001 - see below
                    # Outside the page guard above, so before this an odd
                    # card did not cost its page - it cost the whole combo,
                    # every page already collected included.
                    unreadable = (unreadable[0] + 1, f"{type(exc).__name__}: {exc}")
            if items and not kept:
                # Cards came back and not one could be read: the response
                # shape has moved, and reporting it as a clean empty page
                # would let retirement treat a whole country as sold.
                raise RuntimeError(
                    f"page {page} returned {len(items)} listings and none could be read - {unreadable[1]}"
                )
            if not items:
                break
            page += 1
            if page <= total_pages:
                time.sleep(REQUEST_DELAY_SECONDS)
        if unreadable[0]:
            print(
                f"    autoscout24/{model}/{country}: skipped {unreadable[0]} listing(s) this parser could"
                f" not read ({unreadable[1]}) - kept the other {len(listings)}"
            )
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


def _compose_title(item: dict, *, model: str) -> str:
    """A readable headline for one card.

    `modelVersionInput` is the seller's own trim line and is the best thing
    to show - but it is optional, and an ad with it left blank stored no
    title at all and rendered as "Untitled". The response still identifies
    the car (`make`/`model`), and "Tesla Model 3" is exactly what
    AutoScout24 itself puts on those cards, so fall back to that rather
    than to nothing.
    """
    vehicle = item.get("vehicle") or {}
    version = (vehicle.get("modelVersionInput") or vehicle.get("modelVersionCustom") or "").strip()
    if version:
        return version
    make = (vehicle.get("make") or "Tesla").strip()
    name = (vehicle.get("model") or vehicle.get("modelGroup") or "").strip() or model_display_name(model)
    return f"{make} {name}".strip()


def _offer_url(item: dict) -> str:
    """The ad's own address, or one rebuilt from its id when it has none.

    AutoScout24 normally sends a full slug path. One card in a live run
    sent `/offers/x` instead - a dead link on a real 34.600 EUR listing,
    and one that survived every later scrape because the parser had no
    reason to distrust it. The id-only form redirects to the canonical
    slug (checked against the live site: `/offers/x` 404s, `/offers/{id}`
    answers 200 and lands on the full page), so a card is never a dead
    link and the slug it redirects to carries the colour too.
    """
    path = (item.get("url") or "").strip()
    listing_id = str(item.get("id") or "").strip()
    slug = path.rsplit("/", 1)[-1]
    if path.startswith("/") and len(slug) >= MIN_OFFER_SLUG_LENGTH:
        return "https://www.autoscout24.com" + path
    if listing_id:
        return f"https://www.autoscout24.com/offers/{listing_id}"
    return "https://www.autoscout24.com" + path


def parse_item(item: dict, *, model: str) -> RawListing:
    # `or {}` / `or []`, not just a .get default: the default only applies
    # when the key is ABSENT, and a JSON API says "no seller" by sending
    # null just as readily as by omitting the field. Five of these fields
    # crashed the parser outright on a null - and one bad card here takes
    # the whole combo with it, since the parse happens outside the loop's
    # page guard. Tesla's per-market shape drift was the same lesson.
    if not item.get("id"):
        # An empty id would store as a bare "autoscout24:", one row shared
        # by every such card. Raising hands it to the loop's per-item
        # guard, which counts it and keeps the page.
        raise ValueError("card carries no id to identify it by")
    details = {d["iconName"]: d["data"] for d in (item.get("vehicleDetails") or []) if isinstance(d, dict)}
    first_registration = _parse_month_year(details.get("calendar"))
    country = (item.get("location") or {}).get("countryCode") or ""
    vehicle = item.get("vehicle") or {}

    # No colour field exists in the response; the offer slug carries it.
    url = _offer_url(item)

    return RawListing(
        source="autoscout24",
        source_listing_id=item["id"],
        model=model,
        country=country,
        url=url,
        price_original=float((item.get("price") or {}).get("priceRaw") or 0),
        currency_original=market_currency(country),
        mileage_km=_parse_km(details.get("mileage_odometer")),
        model_year=first_registration.year if first_registration else None,
        first_registration=first_registration,
        variant=vehicle.get("modelVersionInput"),
        title_raw=_compose_title(item, model=model),
        photo_urls=[u for u in (item.get("images") or []) if isinstance(u, str)],
        seller_type=_normalize_seller_type((item.get("seller") or {}).get("type")),
        location=(item.get("location") or {}).get("city"),
        power_kw=_parse_power_kw(details.get("speedometer")),
        color=color_from_autoscout24_url(url),
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
