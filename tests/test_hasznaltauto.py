from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources.hasznaltauto import _split_listings, parse_item

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "hasznaltauto_search_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def listings():
    return _split_listings(FIXTURE_HTML)


def test_fixture_has_three_listings(listings):
    assert len(listings) == 3


def test_parses_private_rwd_listing(listings):
    raw = parse_item(listings[0], model="model_y")
    assert raw is not None
    assert raw.source == "hasznaltauto"
    assert raw.source_listing_id == "23417259"
    assert raw.country == "HU"
    assert raw.currency_original == "HUF"
    assert raw.url == (
        "https://www.hasznaltauto.hu/szemelyauto/tesla/model_y/"
        "tesla_model_y_rwd_automata_garancia_95-os_akku_lfp_60kwh-23417259"
    )
    assert raw.title_raw == "TESLA MODEL Y RWD (Automata) GARANCIA/95%-OS AKKU /LFP/60Kwh!"
    assert raw.variant == raw.title_raw
    assert raw.price_original == 10_390_000.0
    assert raw.mileage_km == 136_000
    assert raw.first_registration == date(2023, 1, 1)
    assert raw.model_year == 2023
    assert raw.power_kw == 220
    assert raw.seller_type == "private"
    assert raw.location is None
    assert raw.photo_urls == ["https://img.hasznaltautocdn.com/118x88/23417259/30441787.jpg"]


def test_parses_price_with_discount_takes_current_not_old_price(listings):
    # This listing has both pricefield-primary-highlighted (10 390 000, current)
    # and pricefield-inactive (10 500 000, crossed-out old price) in the fixture.
    raw = parse_item(listings[0], model="model_y")
    assert raw.price_original == 10_390_000.0


def test_parses_dealer_listing(listings):
    raw = parse_item(listings[2], model="model_y")
    assert raw is not None
    assert raw.source_listing_id == "23452990"
    assert raw.seller_type == "dealer"
    assert raw.price_original == 14_199_999.0
    assert raw.power_kw == 393
    assert raw.first_registration == date(2023, 2, 1)


def test_parses_multiline_description_free_price_listing(listings):
    # This listing's description in the real page contains an embedded
    # newline ("GYÖNYÖRŰ ÚJ SZALON ÁLLAPOT\n91% SOH...") - regression check
    # that DOTALL parsing doesn't choke on it, and it's a plain
    # pricefield-primary (no discount) rather than the highlighted variant.
    raw = parse_item(listings[1], model="model_y")
    assert raw is not None
    assert raw.price_original == 10_899_999.0
    assert raw.mileage_km == 148_000


@pytest.mark.parametrize(
    ("text", "expected"),
    [("10 390 000", 10_390_000), ("136 000", 136_000), ("299", 299), ("", None)],
)
def test_parse_number(text, expected):
    from car_tracker.sources.hasznaltauto import _parse_number

    assert _parse_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Magánszemély", "private"), ("Kereskedés: Sig-Automobiles Kft.", "dealer")],
)
def test_normalize_seller(text, expected):
    from car_tracker.sources.hasznaltauto import _normalize_seller

    assert _normalize_seller(text) == expected
