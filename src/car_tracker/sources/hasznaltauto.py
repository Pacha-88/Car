"""Használtautó.hu source. HU only.

Server-rendered HTML (no JSON blob, like Kleinanzeigen rather than
AutoScout24). Listing rows are deeply nested `<div>`s with no unique
closing marker to regex against, unlike Kleinanzeigen's `<article>` cards
— so instead of matching a start/end pair, the page is split right before
each occurrence of the row's opening marker (`_LISTING_START`), and each
resulting chunk (which runs into the *next* listing's opening tag, or the
page footer for the last one) is searched for this listing's fields. That
works because every field this module reads appears once, near the top of
its own listing's chunk, well before the next chunk boundary — but it does
mean the last chunk on a page contains a lot of trailing footer/script
HTML along for the ride.

This sandbox itself cannot reach hasznaltauto.hu (Cloudflare Bot Management
403s it — see README); the shapes below, and the `/szemelyauto/tesla/{slug}`
+ `/page{N}` URL pattern (confirmed from the page's own `rel="next"`/
`rel="last"` links, not guessed), come from a real response the project
owner fetched from a normal home connection and pasted in
(2026-08-28, Model Y). Model 3's slug is inferred by the same naming
convention, not directly confirmed.

Known gaps, not solved here:
- No used-vs-new filter is applied. The page title itself says "Eladó új
  és használt" ("new and used for sale") — results mix both, and the
  search form has a `hasznalt_jarmu` (used) checkbox, but it's submitted
  through a different endpoint (a POST form) than the clean URL this
  module uses, and guessing the right query-param equivalent without
  verification felt worse than leaving it alone.
- No per-listing location: unlike the other three sources, search results
  here don't surface a city/place name, only a "distance from you" widget
  that needs a postcode this fetch doesn't supply.
"""

from __future__ import annotations

import random
import re
import time
from datetime import date
from html import unescape

import httpx

from car_tracker.normalize.color import normalize_color
from car_tracker.normalize.currency import market_currency
from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.sources.fetch import fetch_html, save_for_diagnosis
from car_tracker.sources.http import build_client

BASE_URL = "https://www.hasznaltauto.hu/szemelyauto/tesla"
MODEL_SLUGS = {"model_y": "model_y", "model_3": "model_3"}  # model_3 unconfirmed

# Raised from 2.0 after a real 28-page run from the owner's home connection
# drew three Cloudflare challenges (model_y page 12, model_3 pages 4 and
# 13) - and the last one could not be cleared, which cost the whole
# model_3 combo. Every extra second here is cheaper than a manual puzzle,
# and far cheaper than a failed combo.
REQUEST_DELAY_SECONDS = 3.5

# A listing row is any <div> whose class list contains "talalati-sor" - as a
# TOKEN, not as the contiguous string 'class="row talalati-sor'. The server
# writes `class="row talalati-sor kiemelt"`, but a browser re-serializes the
# attribute in classList order the moment any script touches it, so one
# `classList.add()` anywhere on the page turns that literal into a string
# that matches nothing. This module reads pages through a real browser (see
# fetch.py), i.e. exactly the DOM where that can happen.
_LISTING_START_RE = re.compile(r'<div[^>]*\sclass="(?:[^"]*\s)?talalati-sor(?:\s[^"]*)?"', re.I)
_HIRKOD_RE = re.compile(r'data-hirkod="(\d+)"')
# The ad number is the tail of every listing URL
# (".../tesla_model_y_rwd_..._60kwh-23417259"), which is a far better place
# to read it from than data-hirkod: that attribute lives on the "parkolo"
# button inside <span class="parking-button-on-mobile">, i.e. markup the
# desktop DOM has no reason to keep. data-hirkod stays as the fallback.
_URL_ID_RE = re.compile(r"-(\d{5,})/?$")
# <h3> carried no attributes in the sample this was built from; requiring
# that exact tag would drop every row the day the site adds a class to it,
# and the anchor text is allowed to contain markup for the same reason.
_TITLE_URL_RE = re.compile(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>', re.S)
_REG_DATE_RE = re.compile(r'<span class="info[^"]*">\s*(\d{4})/(\d{1,2}),\s*</span>')
_POWER_RE = re.compile(r'<span class="info[^"]*">\s*(\d+)\s*kW,\s*</span>')
_MILEAGE_RE = re.compile(r"<abbr[^>]*>([\d\s\u00a0]+)\s*km</abbr>")
# Three ways to find the asking price, tried in order. A single pattern
# pinned to `pricefield-primary">` is what failed on the live page: the
# markup still had rows, ids and titles exactly as sampled, and only the
# price would not match - so one more class on that div, or one tag wrapped
# around the number, was enough to lose all 25 cars on every page.
#
# 1. the primary price field, whatever else its class list or attributes say
# 2. any pricefield that is not the struck-through old price
# 3. no class at all: the first "<number> Ft" big enough to be a car
_PRICE_PRIMARY_RE = re.compile(r"pricefield-primary(?:-highlighted)?\b[^>]*>(.{0,160}?)Ft", re.S | re.I)
_PRICE_ANY_FIELD_RE = re.compile(r'class="[^"]*\bpricefield-(?!inactive)[\w-]*"[^>]*>(.{0,160}?)Ft', re.S | re.I)
_PRICE_BARE_RE = re.compile(r"([\d][\d\s\u00a0.]{5,})\s*Ft", re.I)
# A used Tesla in Hungary is millions of forints. The floor keeps layer 3
# off a monthly finance instalment or a documentation fee, which are the
# other numbers on a row that end in "Ft".
_MIN_PLAUSIBLE_HUF = 1_000_000
_DESCRIPTION_RE = re.compile(r'talalati-sor__leiras"[^>]*>(.*?)</div>', re.S)
_SELLER_RE = re.compile(r'trader-name">\s*([^<]+?)\s*</span>')
_IMAGE_RE = re.compile(r'<img class="img-responsive" src="([^"]+)"')


# The result pages say how many there are, in their own <head>:
#   <link href="/szemelyauto/tesla/model_y/page15" rel="last">
# Walking past that is how a clean 15-page scrape turned into a failure -
# page16 answers HTTP 404 with a 144 KB body, which every block check
# rightly reads as "refused", and the whole combo (fifteen good pages of
# it) was thrown away over a page that was never supposed to be requested.
_LAST_PAGE_RE = re.compile(r'<link[^>]*\brel="last"[^>]*>|<link[^>]*\brel=.last.[^>]*>', re.I)
_PAGE_NUM_RE = re.compile(r"/page(\d+)")
_NEXT_LINK_RE = re.compile(r'<link[^>]*\brel="next"', re.I)


def last_page_number(html: str) -> int | None:
    """The last page this result set has, per the page's own rel="last"."""
    match = _LAST_PAGE_RE.search(html)
    if match:
        page = _PAGE_NUM_RE.search(match.group(0))
        if page:
            return int(page.group(1))
    # No rel="last" but no rel="next" either: this is the only/last page.
    return None if _NEXT_LINK_RE.search(html) else 1


def _paced_delay() -> float:
    """The page gap, jittered.

    Two runs both stalled on page 13 of a 15-page walk. A request exactly
    every 3.5 seconds is a metronome, and a rate limiter counting requests
    per window sees the same shape every time; spreading the gap costs
    nothing and stops the walk arriving at the limit in lockstep. Not a
    proven cure for that stall - a mitigation, and a cheap one.
    """
    return random.uniform(REQUEST_DELAY_SECONDS * 0.6, REQUEST_DELAY_SECONDS * 1.6)


class HasznaltautoSource(Source):
    name = "hasznaltauto"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        # A Hungarian site: a real browser opening it would usually ask for Hungarian first.
        self.client = client or build_client(accept_language="hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "HasznaltautoSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        if country != "HU":
            raise ValueError(f"hasznaltauto only covers HU, got {country!r}")

        listings: list[RawListing] = []
        page = 1
        last_page: int | None = None
        rows_seen = 0
        while max_pages is None or page <= max_pages:
            try:
                html = self.fetch_raw_page(model=model, page=page)
            except Exception as exc:
                # Same rule as the other sources: pages already fetched are
                # real data and must not be thrown away with the failure.
                # It matters most here - every page goes through Cloudflare
                # (see sources/fetch.py), so a challenge appearing at page
                # three, after one and two were served fine, is the normal
                # way this source fails rather than an unlucky one.
                if not listings:
                    raise
                raise PartialResults(listings, f"page {page} failed ({type(exc).__name__}: {exc})") from exc

            if last_page is None:
                last_page = last_page_number(html)

            chunks = _split_listings(html)
            if not chunks:
                break
            rows_seen += len(chunks)
            parsed = [item for c in chunks if (item := parse_item(c, model=model)) is not None]
            if not parsed:
                # Rows on the page, none of them readable: the markup moved
                # under the patterns above. Silence here is how this source
                # spent a whole run walking fifteen pages and storing
                # nothing, reported as "NO data (every attempt was
                # refused)" - which pointed at Cloudflare when the fetch had
                # in fact worked perfectly. Say which field gave out, and
                # keep the page so it can be read.
                unreadable = _unreadable_page_error(html, chunks, page=page, model=model)
                if listings:
                    # Earlier pages read fine; they are real cars at real
                    # prices and go to the caller like any other partial.
                    raise PartialResults(listings, str(unreadable)) from unreadable
                raise unreadable
            listings.extend(parsed)
            note = ""
            if len(parsed) * 3 < len(chunks) * 2:  # fewer than two rows in three
                # A page that yields one car out of twenty-five is a pattern
                # that has half given out, and it went by as a plain "page 1
                # read" line while twenty-four cars quietly vanished. Loud
                # enough to notice, not so loud it fails a usable page.
                note = "  <-- most of this page could NOT be read, the markup is drifting"
            print(f"    hasznaltauto/{model}: page {page} - {len(parsed)} of {len(chunks)} rows read{note}")

            if last_page is not None and page >= last_page:
                break  # the page said so itself; asking for page N+1 gets a 404
            page += 1
            if max_pages is None or page <= max_pages:
                time.sleep(_paced_delay())
        return listings

    def fetch_raw_page(self, *, model: str, page: int = 1) -> str:
        """One page's raw HTML — for inspecting the real response shape.

        Goes through sources/fetch.py rather than this class's httpx client:
        Cloudflare scores the TLS handshake here, and Python's own is
        rejected outright even from a home connection (see that module).
        """
        if model not in MODEL_SLUGS:
            raise ValueError(f"unknown model {model!r}, expected one of {sorted(MODEL_SLUGS)}")
        slug = MODEL_SLUGS[model]
        url = f"{BASE_URL}/{slug}" if page == 1 else f"{BASE_URL}/{slug}/page{page}"
        return fetch_html(url, accept_language="hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7")


def _unreadable_page_error(html: str, chunks: list[str], *, page: int, model: str) -> Exception:
    """Which of the three required fields stopped matching, and where to look."""
    sample = chunks[0]
    href = _href_of(sample) or ""
    wrong_model = href and f"/{MODEL_SLUGS[model]}/" not in href
    if wrong_model:
        # Not a markup change at all: this URL is serving another model's
        # ads. Storing them would file, say, Model Y cars as Model 3.
        served = re.search(r"/szemelyauto/tesla/([^/]+)/", href)
        return RuntimeError(
            f"page {page} is serving {served.group(1) if served else 'another model'}"
            f" ads, not {MODEL_SLUGS[model]} - the URL for this model is wrong."
            f" First ad on it: {href}"
        )
    missing = [
        name
        for name, found in (
            ("listing id (url tail or data-hirkod)", _listing_id(sample, href) is not None),
            ("title/url (<h3><a href=...>)", _TITLE_URL_RE.search(sample) is not None),
            ("price", extract_price_huf(sample) is not None),
        )
        if not found
    ]
    saved = save_for_diagnosis("https://www.hasznaltauto.hu/", html, label=f"unreadable-{model}")
    where = f" Saved at {saved}." if saved else ""
    # The excerpt matters more than the file: whoever runs this reads a
    # terminal, and pasting three lines back is a great deal easier than
    # finding and sending a 150 KB page.
    # The first 400 characters of a row are the same boilerplate every time
    # and say nothing about what broke; show the neighbourhood of whichever
    # field actually failed instead.
    if "price" in missing:
        excerpt = f"price area of the first row: {_price_neighbourhood(sample)}"
    else:
        opening = re.sub(r"\s+", " ", sample[:400])
        excerpt = f"first row starts: {opening}"
    return RuntimeError(
        f"page {page} has {len(chunks)} listing rows but none could be read - "
        f"missing: {', '.join(missing) or 'nothing obvious, the row split may be wrong'}."
        f" The site's markup has moved.{where}\n    {excerpt}"
    )


def _href_of(chunk: str) -> str | None:
    match = _TITLE_URL_RE.search(chunk)
    return match.group(1) if match else None


def _listing_id(chunk: str, href: str | None) -> str | None:
    """Ad number from the URL tail, falling back to data-hirkod."""
    if href:
        from_url = _URL_ID_RE.search(href)
        if from_url:
            return from_url.group(1)
    hirkod = _HIRKOD_RE.search(chunk)
    return hirkod.group(1) if hirkod else None


# The prices are written with non-breaking spaces. The server sends the
# character; a browser's DOM serializer writes it back as the ENTITY, and
# this module reads its pages through a browser - so what actually arrived
# was "10&nbsp;390&nbsp;000&nbsp;Ft", where every pattern here was looking
# for digits and whitespace. That one difference between the pasted sample
# and the live page cost every car on every page.
_NBSP_RE = re.compile(r"&nbsp;|&#160;|&#xa0;", re.I)


def _split_listings(html: str) -> list[str]:
    """Each listing row, from its own opening <div> to the next one's.

    See the module docstring: the rows have no unique closing marker, so the
    page is cut at each row's opening tag instead. Non-breaking spaces are
    normalised to ordinary ones here, once, so no pattern downstream has to
    know which of the two spellings this page happens to use.
    """
    starts = [m.start() for m in _LISTING_START_RE.finditer(html)]
    if not starts:
        return []
    bounds = [*starts, len(html)]
    return [_NBSP_RE.sub(" ", html[bounds[i] : bounds[i + 1]]) for i in range(len(starts))]


def parse_item(chunk: str, *, model: str) -> RawListing | None:
    title_url = _TITLE_URL_RE.search(chunk)
    price = extract_price_huf(chunk)
    listing_id = _listing_id(chunk, title_url.group(1) if title_url else None)
    if not listing_id or not title_url or price is None:
        return None
    # The ad's own URL says which model it is
    # (/szemelyauto/tesla/model_y/tesla_model_y_rwd_...-23417259). Model 3's
    # slug was inferred from Model Y's by naming convention and never
    # confirmed against the site, so a wrong slug that quietly redirected
    # would have filed a page of Model Y ads as Model 3 - and no field in
    # the row itself would have contradicted it. This one does.
    if f"/{MODEL_SLUGS[model]}/" not in title_url.group(1):
        return None

    reg_match = _REG_DATE_RE.search(chunk)
    first_registration = date(int(reg_match.group(1)), int(reg_match.group(2)), 1) if reg_match else None
    power_match = _POWER_RE.search(chunk)
    mileage_match = _MILEAGE_RE.search(chunk)
    seller_match = _SELLER_RE.search(chunk)
    image_match = _IMAGE_RE.search(chunk)
    title_text = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title_url.group(2)))).strip()

    return RawListing(
        source="hasznaltauto",
        source_listing_id=listing_id,
        model=model,
        country="HU",
        url="https://www.hasznaltauto.hu" + title_url.group(1),
        price_original=float(price),
        currency_original=market_currency("HU"),
        mileage_km=_parse_number(mileage_match.group(1)) if mileage_match else None,
        model_year=first_registration.year if first_registration else None,
        first_registration=first_registration,
        # No structured trim field, same situation as Kleinanzeigen - the
        # title feeds the shared central normalize_variant() call.
        variant=title_text,
        title_raw=title_text,
        # Same as Kleinanzeigen: the search row carries no colour field, so
        # the ad's own headline is the only place one can come from.
        color=normalize_color(title_text),
        photo_urls=[image_match.group(1)] if image_match else [],
        seller_type=_normalize_seller(seller_match.group(1)) if seller_match else None,
        location=None,  # not present in search-result markup, see module docstring
        power_kw=int(power_match.group(1)) if power_match else None,
    )


def extract_price_huf(chunk: str) -> int | None:
    """The asking price in forints, or None if nothing in the row looks like one."""
    for pattern in (_PRICE_PRIMARY_RE, _PRICE_ANY_FIELD_RE):
        for match in pattern.finditer(chunk):
            price = _parse_number(_strip_tags(match.group(1)))
            if price:
                return price
    for match in _PRICE_BARE_RE.finditer(chunk):
        price = _parse_number(match.group(1))
        if price and price >= _MIN_PLAUSIBLE_HUF:
            return price
    return None


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _price_neighbourhood(raw_chunk: str) -> str:
    """What the row says around its "Ft"s - for when none of the three worked."""
    chunk = _NBSP_RE.sub(" ", raw_chunk)
    seen = [re.sub(r"\s+", " ", chunk[max(0, m.start() - 90) : m.end() + 10]) for m in _PRICE_BARE_RE.finditer(chunk)]
    if not seen:
        seen = [re.sub(r"\s+", " ", chunk[max(0, m.start() - 40) : m.start() + 90]) for m in re.finditer(r"Ft", chunk)]
    return " || ".join(seen[:3]) if seen else "no \"Ft\" anywhere in the row"


def _parse_number(text: str) -> int | None:
    """"10 390 000" -> 10390000. Dots group thousands in Hungarian too."""
    digits = re.sub(r"[\s\u00a0.]+", "", text)
    return int(digits) if digits.isdigit() else None


def _normalize_seller(text: str) -> str:
    return "dealer" if text.startswith("Kereskedés") else "private"
