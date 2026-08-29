from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources.autoscout24 import (
    AutoScout24Source,
    _extract_page_props,
    _offer_url,
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


# --- colour, read out of the offer slug -----------------------------------
# The response carries no colour field anywhere, but AutoScout24 builds its
# slugs as {make}-{model}-{version}-{fuel}-{colour}-cat_ma…mo…-{uuid}. Of 621
# real listings exactly one had a colour before this, so the dashboard's
# colour filter offered "Unknown" for 620 cars and "Black" for one.


def _item(url: str) -> dict:
    return {
        "id": "x",
        "vehicle": {"make": "Tesla", "model": "Model Y", "modelVersionInput": "Long Range AWD"},
        "price": {"priceRaw": 30000},
        "location": {"countryCode": "DE", "city": "Berlin"},
        "images": [],
        "vehicleDetails": [],
        "seller": {"type": "Dealer"},
        "url": url,
    }


def test_the_colour_comes_out_of_the_slug():
    raw = parse_item(
        _item("/offers/tesla-model-y-standard-range-rwd-1-hand-electric-white-cat_ma51520mo75320-abc-1"),
        model="model_y",
    )
    assert raw.color == "white"


def test_a_listing_with_no_recorded_colour_stays_unknown():
    """Then the slug ends in the fuel word instead, and inventing a colour
    from it would be worse than an honest Unknown."""
    raw = parse_item(
        _item("/offers/tesla-model-3-long-range-awd-514pk-electric-cat_ma51520mo74665-abc-1"),
        model="model_3",
    )
    assert raw.color is None


def test_the_colour_and_the_url_come_from_the_same_string():
    """Regression guard: the url is built once and read twice, so a future
    edit cannot leave the stored link and the colour disagreeing."""
    raw = parse_item(_item("/offers/tesla-model-y-x-electric-grey-cat_ma51520mo75320-abc-1"), model="model_y")
    assert raw.color == "grey"
    assert raw.url.endswith("/offers/tesla-model-y-x-electric-grey-cat_ma51520mo75320-abc-1")
    assert raw.url.startswith("https://www.autoscout24.com")


# --- a null-valued field is not a missing one -----------------------------
# `.get(key, default)` only applies its default when the key is ABSENT, and
# a JSON API says "no seller" by sending null just as readily as by leaving
# the field out. Five of these crashed the parser - and the parse happens
# outside the page guard, so one bad card cost the whole combo, every page
# already collected included. Tesla's per-market shape drift, again.

_HEALTHY_ITEM = {
    "id": "x",
    "url": "/offers/tesla-model-y-white-cat_ma51520mo75320-abc",
    "price": {"priceRaw": 40000},
    "vehicleDetails": [{"iconName": "calendar", "data": "03/2024"}],
    "vehicle": {"modelVersionInput": "Long Range"},
    "location": {"countryCode": "DE", "city": "Berlin"},
    "images": ["https://x/1.jpg"],
    "seller": {"type": "dealer"},
}


@pytest.mark.parametrize(
    "field", ["images", "vehicleDetails", "location", "vehicle", "price", "seller", "url"]
)
def test_a_null_valued_field_does_not_crash_the_parser(field):
    raw = parse_item({**_HEALTHY_ITEM, field: None}, model="model_y")
    assert raw.source_listing_id == "x"


def test_photo_urls_is_always_a_list_of_strings():
    """photoUrls: null reaches the dashboard as `listing.photoUrls[0]`,
    which throws and takes the whole grid down with it."""
    assert parse_item({**_HEALTHY_ITEM, "images": None}, model="model_y").photo_urls == []
    assert parse_item({**_HEALTHY_ITEM, "images": ["a", None, "b"]}, model="model_y").photo_urls == ["a", "b"]


def test_one_unreadable_card_does_not_cost_the_page(monkeypatch, capsys):
    source = AutoScout24Source()

    def _one_page(*, model, country, page=1):
        return {"numberOfPages": 1, "listings": [_HEALTHY_ITEM, "a bare string", {**_HEALTHY_ITEM, "id": "y"}]}

    monkeypatch.setattr(source, "fetch_raw_page", _one_page)
    listings = source.fetch_listings(model="model_y", country="DE")

    assert [raw.source_listing_id for raw in listings] == ["x", "y"]
    assert "skipped 1 listing" in capsys.readouterr().out


def test_a_page_where_nothing_parses_is_an_error_not_an_empty_page(monkeypatch):
    """Cards came back and none could be read: the shape has moved. Calling
    that an empty page would let retirement treat a country as sold."""
    source = AutoScout24Source()
    monkeypatch.setattr(
        source, "fetch_raw_page", lambda **_: {"numberOfPages": 1, "listings": ["nope", "also nope"]}
    )
    with pytest.raises(RuntimeError, match="none could be read"):
        source.fetch_listings(model="model_y", country="DE")


# --- a card must never be a dead link --------------------------------------


def test_a_full_offer_path_is_used_as_sent():
    item = {"url": "/offers/tesla-model-y-long-range-awd-electric-white-cat_ma51520mo75320-abc", "id": "u"}
    assert _offer_url(item) == "https://www.autoscout24.com" + item["url"]


def test_a_placeholder_path_is_rebuilt_from_the_listing_id():
    """One live card sent `/offers/x` - a 404 on a real 34.600 EUR listing,
    which survived every later scrape because the parser had no reason to
    distrust it. The id-only form redirects to the canonical slug."""
    item = {"url": "/offers/x", "id": "eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe"}
    assert _offer_url(item) == "https://www.autoscout24.com/offers/eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe"


def test_a_missing_path_is_rebuilt_too():
    for missing in (None, "", "   "):
        item = {"url": missing, "id": "eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe"}
        assert _offer_url(item).endswith("/offers/eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe")


def test_parse_item_carries_the_rebuilt_url_through():
    listing = parse_item({"id": "eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe", "url": "/offers/x"}, model="model_y")
    assert listing.url == "https://www.autoscout24.com/offers/eaa83b9c-ea2f-4cd7-a277-25c7bd909ebe"
