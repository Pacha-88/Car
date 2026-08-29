"""parse_item() tests.

Fixtures below are modeled on real field names/shapes from a live Tesla
inventory response (DE, Model Y, 2026-08-28, shared by the project owner
after running the query this module builds) — not a byte-exact capture of
it, since the response was shared as a pasted object-tree rather than raw
JSON. The field names and per-field shapes are real; some values are
representative rather than transcribed.
"""

from datetime import date

import pytest

from car_tracker.sources import tesla as tesla_module
from car_tracker.sources.base import PartialResults
from car_tracker.sources.tesla import PAGE_SIZE, TeslaSource, parse_item

LONG_RANGE_ITEM = {
    "Model": "my",
    "VIN": "XP7YGCEK2NB011633",
    "Year": 2022,
    "Price": 29900,
    "CurrencyCode": "EUR",
    "Odometer": 117997,
    "OdometerType": "Km",
    "OdometerTypeShort": "km",
    "PAINT": ["BLACK"],
    "TrimName": "Maximale Reichweite Allradantrieb",
    "TrimVariantCode": "LR_AWD",
    "City": "Holzwickede",
    "FirstRegistrationDate": "2022-07-18T00:00:00",
    "EmissionsData": {"power": 316, "mass": 2054, "efficiency_class": "A+"},
    "VehiclePhotos": [
        {
            "imageUrl": "https://mytcore-inventory-assests.tesla.com/inventory/used/inspection/image/0b7308e5-24b4-4be8-80f8-e8fe51107dd9",
            "pictureType": "Front Full View",
        },
        {
            "imageUrl": "https://mytcore-inventory-assests.tesla.com/inventory/used/inspection/image/653a543a-9bf2-44c9-be13-64210cabb98f",
            "pictureType": "Full View of Driver Side Rear Corner",
        },
    ],
}

RWD_ITEM_MINIMAL = {
    "Model": "my",
    "VIN": "LRWYGCFS5PC782682",
    "Year": 2023,
    "Price": 30600,
    "CurrencyCode": "EUR",
    "Odometer": 51868,
    "OdometerTypeShort": "km",
    "PAINT": [],
    "TrimName": "Model Y Hinterradantrieb",
    "TrimVariantCode": "RWD",
    "City": "Dortmund",
    "FirstRegistrationDate": "2023-04-28T00:00:00",
    "VehiclePhotos": [],
}


def test_long_range_item():
    raw = parse_item(LONG_RANGE_ITEM, model="model_y", country="DE")
    assert raw.source_listing_id == "XP7YGCEK2NB011633"
    assert raw.price_original == 29900
    assert raw.currency_original == "EUR"
    assert raw.mileage_km == 117997
    assert raw.model_year == 2022
    assert raw.first_registration == date(2022, 7, 18)
    assert raw.variant == "LR_AWD"
    assert raw.power_kw == 316
    assert raw.color == "black"
    assert raw.location == "Holzwickede"
    assert len(raw.photo_urls) == 2
    assert raw.photo_urls[0].startswith("https://mytcore-inventory-assests.tesla.com/")


def test_rwd_item_with_missing_optional_fields():
    raw = parse_item(RWD_ITEM_MINIMAL, model="model_y", country="DE")
    assert raw.variant == "RWD"
    assert raw.color is None  # empty PAINT list
    assert raw.photo_urls == []
    assert raw.power_kw is None  # no EmissionsData at all
    assert raw.first_registration == date(2023, 4, 28)


def test_odometer_type_short_preferred_over_odometer_type():
    item = {**LONG_RANGE_ITEM, "OdometerType": "Mi", "OdometerTypeShort": "km"}
    raw = parse_item(item, model="model_y", country="DE")
    assert raw.mileage_km == 117997  # not converted, because the *Short* unit (km) wins


def test_miles_converted_to_km_when_no_short_unit_given():
    item = {**LONG_RANGE_ITEM, "Odometer": 1000}
    del item["OdometerTypeShort"]
    item["OdometerType"] = "Mi"
    raw = parse_item(item, model="model_y", country="DE")
    assert raw.mileage_km == round(1000 * 1.60934)


def test_currency_code_missing_falls_back_to_market_currency():
    item = dict(LONG_RANGE_ITEM)
    del item["CurrencyCode"]
    raw = parse_item(item, model="model_y", country="HU")
    assert raw.currency_original == "HUF"


# --- titles (added after every Tesla card in the dashboard read "Untitled") ---

def test_listing_gets_a_readable_title():
    """Tesla's inventory has no free-text headline, so this source stored
    None and the dashboard rendered "Untitled" for every Tesla car while its
    neighbours showed real ad titles. Compose one from the structured fields
    Tesla does publish."""
    item = {
        "VIN": "X1",
        "Price": 30000,
        "Year": 2022,
        "TrimName": "Long Range AWD",
        "PAINT": ["MIDNIGHT_SILVER"],
    }
    listing = parse_item(item, model="model_y", country="DE")
    assert listing.title_raw == "Model Y · Long Range AWD · 2022 · Midnight Silver"


def test_title_degrades_gracefully_when_fields_are_missing():
    """A sparse listing must still get something better than nothing."""
    listing = parse_item({"VIN": "X2", "Price": 30000}, model="model_3", country="HU")
    assert listing.title_raw == "Model 3"


def test_title_falls_back_to_the_trim_code_when_there_is_no_trim_name():
    listing = parse_item(
        {"VIN": "X3", "Price": 1, "TrimVariantCode": "LR_AWD", "Year": 2024},
        model="model_y",
        country="AT",
    )
    assert "LR_AWD" in listing.title_raw
    assert "2024" in listing.title_raw


# --- partial-page resilience ---------------------------------------------
# Every source keeps what earlier pages returned when a later one fails.
# This one is the likeliest to need it: the inventory API answered a whole
# burst of markets with HTTP 429 on the first live run.


class _FlakyPageSource(TeslaSource):
    """Serves `good_pages` pages, then refuses - like a mid-market 429."""

    def __init__(self, good_pages: int, total: int = 500):
        self._good_pages = good_pages
        self._total = total
        self.attempted: list[int] = []

    def fetch_raw_page(self, *, model: str, country: str, offset: int = 0) -> dict:
        page = offset // PAGE_SIZE + 1
        self.attempted.append(page)
        if page > self._good_pages:
            raise RuntimeError("Client error '429 Too Many Requests'")
        return {
            "total_matches_found": self._total,
            "results": [{"VIN": f"V{page}-{i}", "Price": 30000, "Year": 2022} for i in range(2)],
        }


def test_a_failing_page_keeps_what_earlier_pages_returned(monkeypatch):
    monkeypatch.setattr(tesla_module.time, "sleep", lambda _s: None)
    source = _FlakyPageSource(good_pages=3)

    with pytest.raises(PartialResults) as caught:
        source.fetch_listings(model="model_y", country="DE")

    assert len(caught.value.listings) == 6, "three good pages of two cars each must survive a 429 on the fourth"
    assert "page 4" in caught.value.reason
    assert source.attempted == [1, 2, 3, 4]


def test_a_failure_on_the_very_first_page_still_raises(monkeypatch):
    """Nothing to salvage, and a silent empty list would look like a market
    with no cars in it - which is what retirement keys off."""
    monkeypatch.setattr(tesla_module.time, "sleep", lambda _s: None)
    source = _FlakyPageSource(good_pages=0)
    with pytest.raises(RuntimeError):
        source.fetch_listings(model="model_y", country="DE")
