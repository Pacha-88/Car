from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources.autoscout24 import (
    AutoScout24Source,
    _extract_page_props,
    _parse_km,
    _parse_month_year,
    _parse_power_kw,
    parse_item,
)
from car_tracker.sources.base import PartialResults

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "autoscout24_search_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def page_props():
    return _extract_page_props(FIXTURE_HTML)


@pytest.fixture
def listings(page_props):
    return page_props["listings"]


def test_extract_page_props_reads_pagination_metadata(page_props):
    assert page_props["numberOfResults"] > 0
    assert page_props["numberOfPages"] > 0


def test_extract_page_props_raises_on_unexpected_html():
    with pytest.raises(ValueError):
        _extract_page_props("<html><body>no next data here</body></html>")


def test_parse_rwd_listing(listings):
    raw = parse_item(listings[0], model="model_y")
    assert raw.source == "autoscout24"
    assert raw.source_listing_id == "e83689c2-3a8e-45bc-abd5-7b2a725459e4"
    assert raw.model == "model_y"
    assert raw.country == "DE"
    assert raw.url == (
        "https://www.autoscout24.com/offers/tesla-model-y-standard-range-rwd-1-hand-unfallfrei-electric-white-"
        "cat_ma51520mo75320-e83689c2-3a8e-45bc-abd5-7b2a725459e4"
    )
    assert raw.price_original == 33950
    assert raw.currency_original == "EUR"
    assert raw.mileage_km == 23701
    assert raw.first_registration == date(2024, 1, 1)
    assert raw.model_year == 2024
    assert raw.power_kw == 220
    assert raw.seller_type == "dealer"
    assert raw.location == "Mönchengladbach"
    assert raw.variant == "Standard Range RWD *1. Hand*unfallfrei*"
    assert len(raw.photo_urls) == 2


def test_parse_performance_listing(listings):
    raw = parse_item(listings[1], model="model_y")
    assert raw.price_original == 33900
    assert raw.mileage_km == 49549
    assert raw.first_registration == date(2022, 8, 1)
    assert raw.power_kw == 393
    assert raw.variant == "Dual Performance Dual AWD+PANO+R-KAMERA"


def test_parse_long_range_listing(listings):
    raw = parse_item(listings[2], model="model_y")
    assert raw.price_original == 32650
    assert raw.power_kw == 378
    assert raw.variant == "Long Range AWD *20-Zoll*"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("23,701 km", 23701), ("0 km", 0), (None, None), ("", None)],
)
def test_parse_km(text, expected):
    assert _parse_km(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("01/2024", date(2024, 1, 1)), ("08/2022", date(2022, 8, 1)), (None, None), ("garbage", None)],
)
def test_parse_month_year(text, expected):
    assert _parse_month_year(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("220 kW (299 hp)", 220), ("393 kW (534 hp)", 393), (None, None), ("unknown", None)],
)
def test_parse_power_kw(text, expected):
    assert _parse_power_kw(text) == expected


# --- partial-page resilience --------------------------------------------
# From a real nightly run: autoscout24/model_y/IT raised on a 502 at page 13
# and the whole combo was discarded, losing twelve good pages. Italy simply
# vanished from the dashboard that day.

class _FlakyPageSource(AutoScout24Source):
    """Serves `good_pages` pages, then raises - like a mid-pagination 502."""

    def __init__(self, good_pages: int):
        self._good_pages = good_pages
        self.attempted: list[int] = []

    def fetch_raw_page(self, *, model: str, country: str, page: int = 1) -> dict:
        self.attempted.append(page)
        if page > self._good_pages:
            raise RuntimeError("Server error '502 Bad Gateway'")
        return {
            "numberOfPages": 99,
            "listings": [
                {
                    "id": f"p{page}-{i}",
                    "vehicle": {"modelVersionInput": "Long Range AWD"},
                    "price": {"priceRaw": 30000},
                    "location": {"countryCode": country, "city": "Rome"},
                    "images": [f"https://img/{page}-{i}.jpg"],
                    "vehicleDetails": [],
                    "seller": {"type": "dealer"},
                    "url": f"/offers/{page}-{i}",
                }
                for i in range(2)
            ],
        }


def test_a_failing_page_keeps_the_listings_earlier_pages_returned():
    source = _FlakyPageSource(good_pages=3)
    with pytest.raises(PartialResults) as caught:
        source.fetch_listings(model="model_y", country="IT")
    assert len(caught.value.listings) == 6, "three good pages of two listings each must survive"
    assert "page 4" in caught.value.reason
    assert source.attempted == [1, 2, 3, 4]  # stopped at the first failure


def test_a_failure_on_the_very_first_page_still_raises():
    """Nothing to salvage, and silence would let a fully broken source look
    like a source with no cars - which is what retirement keys off."""
    source = _FlakyPageSource(good_pages=0)
    with pytest.raises(RuntimeError):
        source.fetch_listings(model="model_y", country="IT")
