from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources import hasznaltauto as hasznaltauto_module
from car_tracker.sources.base import PartialResults
from car_tracker.sources.hasznaltauto import HasznaltautoSource, _split_listings, parse_item

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


# --- partial-page resilience ---------------------------------------------
# Every page here goes through Cloudflare (see sources/fetch.py), so a
# challenge appearing at page three after one and two were served is the
# normal way this source fails - and it used to discard both good pages.


class _FlakyPageSource(HasznaltautoSource):
    def __init__(self, good_pages: int, page_html: str):
        self._good_pages = good_pages
        self._page_html = page_html
        self.attempted: list[int] = []

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        self.attempted.append(page)
        if page > self._good_pages:
            raise RuntimeError("blocked at both stages")
        return self._page_html


def test_a_failing_page_keeps_the_cars_earlier_pages_returned(monkeypatch):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    source = _FlakyPageSource(good_pages=2, page_html=FIXTURE_HTML)

    with pytest.raises(PartialResults) as caught:
        source.fetch_listings(model="model_y", country="HU")

    assert caught.value.listings, "two good pages of Hungarian cars must survive"
    assert "page 3" in caught.value.reason
    assert source.attempted == [1, 2, 3]


def test_a_failure_on_the_very_first_page_still_raises(monkeypatch):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    source = _FlakyPageSource(good_pages=0, page_html=FIXTURE_HTML)
    with pytest.raises(RuntimeError):
        source.fetch_listings(model="model_y", country="HU")


# --- pagination: stop where the page says the results stop ----------------


class _CountingSource(HasznaltautoSource):
    """Serves the fixture for any page; records what was asked for."""

    def __init__(self, page_html: str):
        self._page_html = page_html
        self.attempted: list[int] = []

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        self.attempted.append(page)
        return self._page_html


def test_last_page_is_read_from_the_page_itself():
    # The fixture's <head> carries <link ... /page15 rel="last">.
    assert hasznaltauto_module.last_page_number(FIXTURE_HTML) == 15


def test_last_page_number_without_a_next_link_is_page_one():
    assert hasznaltauto_module.last_page_number("<html><head></head><body></body></html>") == 1


def test_last_page_number_with_a_next_but_no_last_is_unknown():
    html = '<html><head><link href="/szemelyauto/tesla/model_y/page2" rel="next"></head></html>'
    assert hasznaltauto_module.last_page_number(html) is None


def test_walk_stops_at_the_advertised_last_page(monkeypatch):
    """Page 16 of a 15-page result set answers 404 with a full-size body.

    Every block check reads that as a refusal, so a clean fifteen-page
    scrape was reported as "blocked at both stages" and its listings thrown
    away. The page says where it ends; believe it.
    """
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    source = _CountingSource(FIXTURE_HTML)

    listings = source.fetch_listings(model="model_y", country="HU")

    assert source.attempted == list(range(1, 16)), "must not ask for page 16"
    assert len(listings) == 15 * 3


def test_max_pages_still_wins_over_the_advertised_last_page(monkeypatch):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    source = _CountingSource(FIXTURE_HTML)
    source.fetch_listings(model="model_y", country="HU", max_pages=2)
    assert source.attempted == [1, 2]


# --- reading a row does not depend on mobile-only markup ------------------


def test_listing_id_comes_from_the_url_when_data_hirkod_is_absent():
    """data-hirkod sits on a button inside .parking-button-on-mobile.

    A desktop DOM has no reason to keep that markup, and losing it used to
    make every row unreadable. The ad number is also the tail of the URL.
    """
    chunk = _split_listings(FIXTURE_HTML)[0]
    without = chunk.replace('data-hirkod="23417259"', "")
    assert 'data-hirkod' not in without
    parsed = parse_item(without, model="model_y")
    assert parsed is not None
    assert parsed.source_listing_id == "23417259"


def test_a_title_tag_that_grew_attributes_still_parses():
    chunk = _split_listings(FIXTURE_HTML)[0].replace("<h3>", '<h3 class="cim">')
    parsed = parse_item(chunk, model="model_y")
    assert parsed is not None
    assert parsed.title_raw.startswith("TESLA MODEL Y RWD")


# --- a page full of rows that cannot be read is an error, not silence -----


def test_unreadable_rows_raise_instead_of_returning_nothing(monkeypatch):
    """Fifteen pages fetched, zero listings stored, reported as a block.

    The fetch had worked perfectly; the markup had moved. Silence sent the
    owner hunting Cloudflare. Now it names the field that gave out.
    """
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    broken = FIXTURE_HTML.replace("pricefield-primary", "pricefield-renamed")
    source = _CountingSource(broken)

    with pytest.raises(RuntimeError, match="listing rows but none could be read"):
        source.fetch_listings(model="model_y", country="HU")

    assert source.attempted == [1], "no point walking fourteen more pages of the same"


def test_unreadable_rows_after_good_pages_keep_those_pages(monkeypatch):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    broken = FIXTURE_HTML.replace("pricefield-primary", "pricefield-renamed")

    class _GoodThenBroken(_CountingSource):
        def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
            self.attempted.append(page)
            return FIXTURE_HTML if page <= 2 else broken

    source = _GoodThenBroken(FIXTURE_HTML)
    with pytest.raises(PartialResults) as caught:
        source.fetch_listings(model="model_y", country="HU")

    assert len(caught.value.listings) == 6, "the two readable pages are still real cars"
    assert "none could be read" in caught.value.reason


# --- the row split must survive a browser touching classList --------------


@pytest.mark.parametrize(
    "class_value, is_row",
    [
        ("row talalati-sor kiemelt", True),   # what the server writes
        ("kiemelt talalati-sor row", True),   # what a classList touch re-serializes to
        ("talalati-sor", True),
        ("talalati-sor__leiras", False),      # the description block, not a row
        ("talalati-sorozat", False),
        ("row talalatisor-adatok", False),
    ],
)
def test_row_split_matches_the_class_token_not_a_literal_string(class_value, is_row):
    """The rows were found by the literal 'class="row talalati-sor'.

    A browser rewrites the whole class attribute in classList order as soon
    as any script adds or removes a class, so one classList.add() anywhere
    on the page turned that literal into a string matching nothing - and
    this source reads its pages through a real browser.
    """
    found = bool(hasznaltauto_module._LISTING_START_RE.search(f'<div class="{class_value}">'))
    assert found is is_row


def test_reordered_row_classes_still_parse():
    shuffled = FIXTURE_HTML.replace('class="row talalati-sor kiemelt"', 'class="kiemelt talalati-sor row"')
    rows = _split_listings(shuffled)
    assert len(rows) == 3
    assert all(parse_item(r, model="model_y") is not None for r in rows)
