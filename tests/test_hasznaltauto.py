import re
from datetime import date
from pathlib import Path

import pytest

from car_tracker.sources import hasznaltauto as hasznaltauto_module
from car_tracker.sources.base import PartialResults
from car_tracker.sources.hasznaltauto import (
    HasznaltautoSource,
    _split_listings,
    extract_price_huf,
    parse_item,
)

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "hasznaltauto_search_sample.html").read_text(encoding="utf-8")
# The same page as a BROWSER hands it back - which is how this source
# actually reads it. See the fixture's own header.
BROWSER_DOM_HTML = (Path(__file__).parent / "fixtures" / "hasznaltauto_browser_dom_sample.html").read_text(
    encoding="utf-8"
)


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


def _without_prices(html: str) -> str:
    """Every "10 390 000 Ft" replaced by words - no number left to find."""
    return re.sub(r"[\d][\d\s\u00a0.]{4,}\s*Ft", "ár egyeztetés alatt Ft", html)


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
    # Renaming the class is not enough any more - the price falls back to a
    # class-free scan - so take the number away entirely.
    broken = _without_prices(FIXTURE_HTML)
    source = _CountingSource(broken)

    with pytest.raises(RuntimeError, match="listing rows but none could be read"):
        source.fetch_listings(model="model_y", country="HU")

    assert source.attempted == [1], "no point walking fourteen more pages of the same"


def test_unreadable_rows_after_good_pages_keep_those_pages(monkeypatch):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    broken = _without_prices(FIXTURE_HTML)

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


# --- the price is the field that actually broke on the live site ----------
# The rows, ids and titles came through exactly as sampled; only
# `pricefield-primary">` would not match, and one pattern pinned to that
# exact string lost all 25 cars on every page. Three layers now: the
# primary field whatever else its class list says, any pricefield that is
# not the struck-through old price, and failing both, the first number in
# the row big enough to be a car.


@pytest.mark.parametrize(
    "markup, expected",
    [
        ('<div class="pricefield-primary-highlighted">10 390 000 Ft</div>', 10_390_000),
        ('<div class="pricefield-primary text-right">10 390 000 Ft</div>', 10_390_000),
        ('<div class="pricefield-primary" data-x="1">10 390 000 Ft</div>', 10_390_000),
        ('<div class="pricefield-primary"><span>10 390 000</span> Ft</div>', 10_390_000),
        ('<div class="pricefield-primary">10.390.000 Ft</div>', 10_390_000),
        ('<div class="pricefield-primary">10\u00a0390\u00a0000\u00a0Ft</div>', 10_390_000),
        ('<div class="ad-price-main">10 390 000 Ft</div>', 10_390_000),
    ],
)
def test_price_survives_the_shapes_a_class_change_can_take(markup, expected):
    assert extract_price_huf(markup) == expected


def test_the_struck_through_old_price_never_wins():
    row = '<div class="pricefield-inactive">10 500 000 Ft</div><div class="pricefield-primary">10 390 000 Ft</div>'
    assert extract_price_huf(row) == 10_390_000


def test_a_monthly_instalment_is_not_mistaken_for_a_price():
    """Layer three has no class to go on, so it needs a floor.

    A used Tesla in Hungary is millions of forints; a finance instalment or
    a paperwork fee is not, and both end in "Ft" on the same row.
    """
    assert extract_price_huf('<div class="finance">havi 89 000 Ft</div>') is None
    row = '<div class="finance">havi 89 000 Ft</div><div class="whatever">10 390 000 Ft</div>'
    assert extract_price_huf(row) == 10_390_000


def test_an_unreadable_price_says_what_the_row_says_around_its_Ft(monkeypatch):
    """The old message quoted the first 400 characters of the row - which
    are identical boilerplate on every listing and said nothing at all."""
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    # Strip every price from the rows, leaving something Ft-shaped behind.
    broken = _without_prices(FIXTURE_HTML)

    class _Broken(_CountingSource):
        def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
            self.attempted.append(page)
            return broken

    with pytest.raises(RuntimeError) as caught:
        _Broken(broken).fetch_listings(model="model_y", country="HU")
    message = str(caught.value)
    assert "missing: price" in message
    assert "price area of the first row" in message
    assert "pricefield" in message, "the quoted neighbourhood must show the real markup"


# --- the shape the live site actually serves ------------------------------
# The server writes a non-breaking space as the character; page.content()
# writes it back as the &nbsp; ENTITY. Every pattern here was looking for
# digits and whitespace, so "10&nbsp;390&nbsp;000&nbsp;Ft" matched nothing -
# and this source reads its pages through a browser. That single difference
# between the pasted sample and the live page cost every car on every page.


def test_a_browser_serialized_page_parses_exactly_like_the_server_one():
    server = [parse_item(c, model="model_y") for c in _split_listings(FIXTURE_HTML)]
    browser = [parse_item(c, model="model_y") for c in _split_listings(BROWSER_DOM_HTML)]

    assert all(row is not None for row in browser), "&nbsp; must not make a row unreadable"
    assert len(browser) == len(server) == 3
    for from_server, from_browser in zip(server, browser, strict=True):
        assert from_browser.source_listing_id == from_server.source_listing_id
        assert from_browser.price_original == from_server.price_original
        assert from_browser.mileage_km == from_server.mileage_km
        assert from_browser.first_registration == from_server.first_registration
        assert from_browser.power_kw == from_server.power_kw


def test_the_entity_price_is_the_asking_price_not_the_struck_through_one():
    assert "10&nbsp;500&nbsp;000" in BROWSER_DOM_HTML, "the fixture must carry the old price to be beaten"
    row = _split_listings(BROWSER_DOM_HTML)[0]
    assert parse_item(row, model="model_y").price_original == 10_390_000


def test_a_browser_serialized_walk_reads_every_page(monkeypatch, capsys):
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    source = _CountingSource(BROWSER_DOM_HTML)

    listings = source.fetch_listings(model="model_y", country="HU")

    assert source.attempted == list(range(1, 16))
    assert len(listings) == 15 * 3
    assert "could NOT be read" not in capsys.readouterr().out


def test_a_page_that_yields_almost_nothing_says_so(capsys, monkeypatch):
    """One car read out of twenty-five went by as a plain "page 1 read" line.

    That is a pattern half given out, and twenty-four cars vanishing
    quietly - which is exactly how it showed up on model_3.
    """
    monkeypatch.setattr(hasznaltauto_module.time, "sleep", lambda _s: None)
    rows = _split_listings(BROWSER_DOM_HTML)
    # Two rows readable, three not: below half.
    thin = rows[0] + _without_prices(rows[1]) + _without_prices(rows[2]) + rows[0].replace("23417259", "23417260")
    page = f'<html><head><link href="/szemelyauto/tesla/model_y/page1" rel="last"></head><body>{thin}</body></html>'

    _CountingSource(page).fetch_listings(model="model_y", country="HU")

    assert "most of this page could NOT be read" in capsys.readouterr().out
