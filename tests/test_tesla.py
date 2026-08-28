"""parse_item() tests.

Fixtures below are modeled on real field names/shapes from a live Tesla
inventory response (DE, Model Y, 2026-08-28, shared by the project owner
after running the query this module builds) — not a byte-exact capture of
it, since the response was shared as a pasted object-tree rather than raw
JSON. The field names and per-field shapes are real; some values are
representative rather than transcribed.
"""

from datetime import date

from car_tracker.sources.tesla import parse_item

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
