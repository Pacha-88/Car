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


# --- the listing URL and the photo fallback -------------------------------
# The first URL guess ("/de/inventory/used/my/{vin}") 404ed on every real
# click - the inventory path is the search page and takes no VIN. And cars
# with no inspection photos rendered as bare placeholders even though
# Tesla's own site shows them as a configurator render.

from car_tracker.sources.tesla import listing_url, stock_photo


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("DE", "https://www.tesla.com/de_DE/my/order/VIN123?titleStatus=used"),
        ("AT", "https://www.tesla.com/de_AT/my/order/VIN123?titleStatus=used"),
        ("HU", "https://www.tesla.com/hu_HU/my/order/VIN123?titleStatus=used"),
    ],
)
def test_listing_url_is_the_order_deep_link(country, expected):
    assert listing_url("model_y", country, "VIN123") == expected


def test_listing_url_model_3():
    assert listing_url("model_3", "DE", "V") == "https://www.tesla.com/de_DE/m3/order/V?titleStatus=used"


def test_inspection_photos_win_over_the_render():
    raw = parse_item({**LONG_RANGE_ITEM, "OptionCodeList": "MTY13,PPSW"}, model="model_y", country="DE")
    assert raw.photo_urls[0].startswith("https://mytcore-inventory-assests.tesla.com/")


@pytest.mark.parametrize(
    "codes",
    ["MTY13,PPSW,WY19B", ["MTY13", "PPSW", "WY19B"], "$MTY13, $PPSW , $WY19B"],
)
def test_a_car_with_no_photos_gets_a_configurator_render(codes):
    """The API hands option codes as a comma string; a list and pre-$-prefixed
    codes are accepted too rather than guessed about."""
    item = {**RWD_ITEM_MINIMAL, "OptionCodeList": codes}
    raw = parse_item(item, model="model_y", country="DE")
    assert len(raw.photo_urls) == 1
    url = raw.photo_urls[0]
    assert url.startswith("https://static-assets.tesla.com/configurator/compositor?")
    assert "options=$MTY13,$PPSW,$WY19B" in url
    assert "model=my" in url


def test_no_photos_and_no_codes_keeps_the_placeholder():
    raw = parse_item(RWD_ITEM_MINIMAL, model="model_y", country="DE")
    assert raw.photo_urls == []


@pytest.mark.parametrize(
    "field",
    [
        {"OptionCodeData": [{"code": "MTY13", "group": "TRIM"}, {"code": "PPSW", "group": "PAINT"}]},
        {"OptionCodeListDisplayOnly": "MTY13,PPSW"},
    ],
)
def test_alternative_option_code_fields_also_produce_a_render(field):
    """The pasted sample lacked the code field and tesla.com is unreachable
    from the sandbox, so every spelling the API has used is accepted."""
    raw = parse_item({**RWD_ITEM_MINIMAL, **field}, model="model_y", country="DE")
    assert len(raw.photo_urls) == 1
    assert "$MTY13,$PPSW" in raw.photo_urls[0]


def test_a_run_nameses_the_fields_of_a_photoless_car(capsys):
    """The person running scrape-local at home is the only one who ever sees
    a real item, so their log carries the diagnosis."""
    TeslaSource._report_photoless(
        [parse_item(RWD_ITEM_MINIMAL, model="model_y", country="DE")],
        RWD_ITEM_MINIMAL,
        model="model_y",
        country="DE",
    )
    out = capsys.readouterr().out
    assert "1 of 1 cars have no photos" in out
    assert "'VIN'" in out


# --- per-market field-shape drift ----------------------------------------
# A live AT market failed the whole combo with "'str' object has no
# attribute 'get'": Tesla's inventory API does not answer every market with
# the same shapes, and three fields here trusted one each. Nothing about
# these is exotic - stock_photo already guarded its own field the same way.


@pytest.mark.parametrize(
    "extra, expect",
    [
        ({"PAINT": "MIDNIGHT_SILVER"}, {"color": "silver"}),
        ({"PAINT": ["WHITE"]}, {"color": "white"}),
        ({"PAINT": []}, {"color": None}),
        ({"EmissionsData": "not an object"}, {"power_kw": None}),
        ({"EmissionsData": {"power": 220}}, {"power_kw": 220}),
        ({"EmissionsData": {"power": "220"}}, {"power_kw": 220}),
        ({"EmissionsData": {"power": "n/a"}}, {"power_kw": None}),
    ],
)
def test_odd_field_shapes_do_not_crash_the_market(extra, expect):
    item = {"VIN": "X1", "Price": 40000, "Year": 2024, "TrimName": "Long Range AWD", "Odometer": 1000, **extra}
    raw = parse_item(item, model="model_y", country="AT")
    for field, value in expect.items():
        assert getattr(raw, field) == value


@pytest.mark.parametrize(
    "photos, expected",
    [
        ([{"imageUrl": "https://x/1.jpg"}], ["https://x/1.jpg"]),
        (["https://x/2.jpg", "https://x/3.jpg"], ["https://x/2.jpg", "https://x/3.jpg"]),
        ("not a list", []),
        ([{"noUrl": 1}], []),
    ],
)
def test_vehicle_photos_shapes(photos, expected):
    item = {"VIN": "X1", "Price": 40000, "Year": 2024, "VehiclePhotos": photos}
    raw = parse_item(item, model="model_y", country="AT")
    # An empty result falls through to the compositor render, which is a
    # different thing entirely - so only assert the direct URLs.
    if expected:
        assert raw.photo_urls == expected
    else:
        assert all("static-assets.tesla.com" in u for u in raw.photo_urls)


def test_one_unreadable_car_does_not_cost_the_whole_market(monkeypatch, capsys):
    """A single bad item used to take every car in the market with it."""
    monkeypatch.setattr(tesla_module.time, "sleep", lambda _s: None)
    good = {"VIN": "A", "Price": 40000, "Year": 2024, "Odometer": 1000}
    other = {"VIN": "B", "Price": 41000, "Year": 2024, "Odometer": 2000}

    class _OneRotten(TeslaSource):
        def __init__(self):
            pass

        def fetch_raw_page(self, *, model, country, offset=0):
            return {"results": [good, "a bare string where a car should be", other], "total_matches_found": 3}

    listings = _OneRotten().fetch_listings(model="model_y", country="AT")
    assert [raw.source_listing_id for raw in listings] == ["A", "B"]
    assert "skipped 1 item" in capsys.readouterr().out


def test_a_market_tesla_does_not_serve_is_an_empty_market_not_a_failure(monkeypatch, capsys):
    """HU answers 412 at both stages, every run, while DE and AT answer fine.

    Neither a failure nor a partial: both mark the source incomplete, and a
    market that refuses on every run would then block retirement for all of
    Tesla forever - sold German cars would never leave the dashboard. The
    guard against a genuine API-wide outage is the retirement share cap.
    """
    monkeypatch.setattr(tesla_module.time, "sleep", lambda _s: None)

    class _Refused(TeslaSource):
        def __init__(self):
            pass

        def fetch_raw_page(self, *, model, country, offset=0):
            raise tesla_module.FetchError("blocked at both stages", statuses=(412, 412))

    assert _Refused().fetch_listings(model="model_y", country="HU") == []
    assert "refuses this market" in capsys.readouterr().out


def test_a_real_block_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(tesla_module.time, "sleep", lambda _s: None)

    class _Blocked(TeslaSource):
        def __init__(self):
            pass

        def fetch_raw_page(self, *, model, country, offset=0):
            raise tesla_module.FetchError("blocked at both stages", statuses=(429, 403))

    with pytest.raises(tesla_module.FetchError):
        _Blocked().fetch_listings(model="model_y", country="DE")
