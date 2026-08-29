from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources.base import PartialResults
from car_tracker.sources.kleinanzeigen import KleinanzeigenSource, _ARTICLE_RE, parse_item

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "kleinanzeigen_search_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def articles():
    return _ARTICLE_RE.findall(FIXTURE_HTML)


def test_fixture_has_four_articles(articles):
    assert len(articles) == 4


def test_parses_normal_private_listing(articles):
    raw = parse_item(articles[0], model="model_y")
    assert raw is not None
    assert raw.source == "kleinanzeigen"
    assert raw.source_listing_id == "3486085730"
    assert raw.country == "DE"
    assert raw.currency_original == "EUR"
    assert raw.url == (
        "https://www.kleinanzeigen.de/s-anzeige/tesla-model-y-long-range-awd-quicksilver-ahk/3486085730-216-24604"
    )
    assert raw.title_raw == "Tesla Model Y Long Range AWD – Quicksilver – AHK"
    assert raw.variant == raw.title_raw  # no structured trim field, title feeds normalize_variant() centrally
    assert raw.price_original == 37500.0
    assert raw.mileage_km == 53000
    assert raw.first_registration == date(2023, 3, 1)
    assert raw.model_year == 2023
    assert raw.location == "Horbach"
    assert raw.seller_type == "private"
    assert raw.photo_urls == ["https://img.kleinanzeigen.de/api/v1/prod-ads/images/51/5159439e-59bb-43a4-99c3-9b24b64b3c20?rule=$_59.AUTO"]


def test_filters_out_wanted_ad(articles):
    # tagged "Gesuch" (wanted) - someone looking to buy, not a for-sale listing
    assert parse_item(articles[1], model="model_y") is None


def test_filters_out_listing_with_no_fixed_price(articles):
    # price block is just "VB" (negotiable) with no number at all
    assert parse_item(articles[2], model="model_y") is None


def test_parses_dealer_listing(articles):
    raw = parse_item(articles[3], model="model_y")
    assert raw is not None
    assert raw.seller_type == "dealer"
    assert raw.price_original == 35900.0
    assert raw.mileage_km == 7000
    assert raw.first_registration == date(2023, 9, 1)
    assert raw.location == "Dürnau"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("37.500 € VB", 37500.0), ("35.990 €", 35990.0), ("VB", None), ("", None)],
)
def test_parse_price(text, expected):
    from car_tracker.sources.kleinanzeigen import _parse_price

    assert _parse_price(text) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [(["53.000 km", "EZ 03/2023"], 53000), (["EZ 03/2023"], None), ([], None)],
)
def test_parse_mileage(tags, expected):
    from car_tracker.sources.kleinanzeigen import _parse_mileage

    assert _parse_mileage(tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [(["53.000 km", "EZ 03/2023"], date(2023, 3, 1)), (["53.000 km"], None), ([], None)],
)
def test_parse_first_registration(tags, expected):
    from car_tracker.sources.kleinanzeigen import _parse_first_registration

    assert _parse_first_registration(tags) == expected


# --- partial-page resilience --------------------------------------------
# From a real nightly run: kleinanzeigen/model_y/DE raised on a 403 at page 2
# and the whole combo was discarded, throwing away a good page 1.

class _FlakyPageSource(KleinanzeigenSource):
    def __init__(self, good_pages: int, article_html: str):
        self._good_pages = good_pages
        self._article_html = article_html
        self.attempted: list[int] = []

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        self.attempted.append(page)
        if page > self._good_pages:
            raise RuntimeError("Client error '403 Forbidden'")
        return self._article_html


def test_a_failing_page_keeps_the_ads_earlier_pages_returned():
    source = _FlakyPageSource(good_pages=1, article_html=FIXTURE_HTML)
    with pytest.raises(PartialResults) as caught:
        source.fetch_listings(model="model_y", country="DE")
    assert caught.value.listings, "page 1's ads must survive a 403 on page 2"
    assert source.attempted == [1, 2]


def test_a_failure_on_the_very_first_page_still_raises():
    source = _FlakyPageSource(good_pages=0, article_html=FIXTURE_HTML)
    with pytest.raises(RuntimeError):
        source.fetch_listings(model="model_y", country="DE")
