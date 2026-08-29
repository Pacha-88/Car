"""cli.py's orchestration logic: rate resolution and the scrape-all
daily-cron entry point. Uses a real (temp-file) SQLite engine via
DATABASE_URL, same pattern as test_timeutil.py, rather than mocking the DB
layer away - the thing worth proving is that storage actually happens
through cmd_scrape_all's real code path, not just that it calls functions.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from car_tracker import cli
from car_tracker.db.models import Listing, ListingSnapshot
from car_tracker.db.session import get_engine, init_db, session_scope
from car_tracker.sources.base import PartialResults, RawListing, Source
from car_tracker.timeutil import utc_now


class _FakeOkSource(Source):
    name = "fake_ok"

    def __enter__(self) -> "_FakeOkSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        return [
            RawListing(
                source="fake_ok",
                source_listing_id=f"{model}-{country}",
                model=model,
                country=country,
                url="https://example.com/1",
                price_original=30_000,
                currency_original="EUR",
            )
        ]


class _FakeFailSource(Source):
    name = "fake_fail"

    def __enter__(self) -> "_FakeFailSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        raise RuntimeError("simulated site block")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/scrape_all.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    init_db(get_engine(db_url))
    # The real run paces itself between combos to avoid rate limits; tests
    # exercise the ordering, not the waiting.
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    return db_url


def test_scrape_all_continues_past_one_failing_source_but_still_exits_nonzero(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource, "fake_fail": _FakeFailSource})
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {
            "fake_ok": {"models": ["model_y"], "countries": ["DE"]},
            "fake_fail": {"models": ["model_y"], "countries": ["DE"]},
        },
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    # The failing combo is named in the exit message rather than swallowed...
    assert "fake_fail/model_y/DE" in str(exc_info.value)

    # ...but the working source's listing was still stored despite that failure.
    with session_scope(get_engine(isolated_db)) as session:
        stored_ids = [listing.id for listing in session.execute(select(Listing)).scalars()]
    assert stored_ids == ["fake_ok:model_y-DE"]


def test_scrape_all_exits_zero_when_every_combo_succeeds(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))  # must not raise

    with session_scope(get_engine(isolated_db)) as session:
        stored = list(session.execute(select(Listing)).scalars())
    assert len(stored) == 1


def test_rates_for_country_override_always_wins(monkeypatch):
    def _boom():
        raise AssertionError("must not hit the network when an override is given")

    monkeypatch.setattr(cli, "fetch_latest_rates", _boom)
    rates = cli._rates_for_country("HU", huf_rate_override=0.0026)
    assert rates == {"EUR": 1.0, "HUF": 0.0026}


def test_rates_for_country_skips_ecb_fetch_for_eurozone_country(monkeypatch):
    def _boom():
        raise AssertionError("a eurozone country never needs a non-EUR rate")

    monkeypatch.setattr(cli, "fetch_latest_rates", _boom)
    assert cli._rates_for_country("DE", huf_rate_override=None) == {"EUR": 1.0}


def test_rates_for_country_fetches_ecb_for_non_eurozone_country(monkeypatch):
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0027, "USD": 0.86}))
    rates = cli._rates_for_country("HU", huf_rate_override=None)
    assert rates == {"EUR": 1.0, "HUF": 0.0027, "USD": 0.86}


class _FakeEmptySource(Source):
    """A source that returns nothing - what a silently-blocked site looks like."""

    name = "fake_ok"

    def __enter__(self) -> "_FakeEmptySource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        return []


def _seed_one_listing(db_url: str, *, source: str, seen_at) -> None:
    with session_scope(get_engine(db_url)) as session:
        session.add(
            Listing(
                id=f"{source}:old",
                source=source,
                source_listing_id="old",
                model="model_y",
                country="DE",
                url="https://example.com/old",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                is_active=True,
            )
        )


def _is_active(db_url: str, listing_id: str) -> bool:
    with session_scope(get_engine(db_url)) as session:
        return session.execute(select(Listing.is_active).where(Listing.id == listing_id)).scalar()


def test_scrape_all_retires_listings_the_site_no_longer_lists(isolated_db, monkeypatch):
    """Sold and withdrawn cars must stop being exported, or the dashboard
    fills up with dead listings and the medians drift with them."""
    _seed_one_listing(isolated_db, source="fake_ok", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _is_active(isolated_db, "fake_ok:old") is False, "stale listing should have been retired"
    # ...while the listing this run actually saw stays active.
    assert _is_active(isolated_db, "fake_ok:model_y-DE") is True


def test_scrape_all_never_retires_anything_for_a_source_that_failed(isolated_db, monkeypatch):
    """The dangerous case: a blocked source returns nothing, and "saw
    nothing" must not be read as "everything is gone" - that would wipe a
    whole marketplace off the dashboard on one bad day."""
    _seed_one_listing(isolated_db, source="fake_fail", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_fail": _FakeFailSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_fail": {"models": ["model_y"], "countries": ["DE"]}})

    with pytest.raises(SystemExit):
        cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _is_active(isolated_db, "fake_fail:old") is True, "a failing source must never retire its own listings"


def test_scrape_all_does_not_retire_when_a_source_legitimately_returns_nothing_but_succeeded(
    isolated_db, monkeypatch
):
    """A source that succeeds but genuinely has zero results today *should*
    retire - this pins the difference against the failure case above."""
    _seed_one_listing(isolated_db, source="fake_ok", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeEmptySource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _is_active(isolated_db, "fake_ok:old") is False


def test_retiring_one_source_leaves_other_sources_untouched(isolated_db, monkeypatch):
    _seed_one_listing(isolated_db, source="fake_ok", seen_at=datetime(2026, 1, 1))
    _seed_one_listing(isolated_db, source="other", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _is_active(isolated_db, "fake_ok:old") is False
    assert _is_active(isolated_db, "other:old") is True, "a source not in this run must not be touched"


def test_export_creates_missing_parent_directories(isolated_db, tmp_path):
    """Regression: the first real CI run died here with FileNotFoundError.

    frontend/public/data/ doesn't exist in a fresh clone - the export it
    holds is gitignored generated data, and git doesn't track empty
    directories - so export must create the path, not assume it.
    """
    out = tmp_path / "frontend" / "public" / "data" / "listings.json"
    assert not out.parent.exists()

    cli.cmd_export(argparse.Namespace(out=str(out)))

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["listings"] == []  # empty DB, but the file is well-formed


def test_scrape_all_skips_the_datacenter_blocked_sources_by_default(isolated_db, monkeypatch):
    """The scheduled run must not spend every day re-failing on sources that
    structurally cannot work from CI - that's how a real failure gets lost
    in the noise of expected ones."""
    attempted: list[str] = []

    class _RecordingSource(_FakeOkSource):
        def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None):
            attempted.append(self.name)
            return []

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "DATACENTER_BLOCKED_SOURCES", ("blocked",))
    monkeypatch.setattr(
        cli,
        "SOURCES",
        {"reachable": type("R", (_RecordingSource,), {"name": "reachable"}),
         "blocked": type("B", (_RecordingSource,), {"name": "blocked"})},
    )
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {
            "reachable": {"models": ["model_y"], "countries": ["DE"]},
            "blocked": {"models": ["model_y"], "countries": ["HU"]},
        },
    )

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=False))

    assert attempted == ["reachable"], "the blocked source should not have been contacted"


def test_scrape_local_runs_only_the_datacenter_blocked_sources(isolated_db, monkeypatch):
    attempted: list[str] = []

    class _RecordingSource(_FakeOkSource):
        def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None):
            attempted.append(self.name)
            return []

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "DATACENTER_BLOCKED_SOURCES", ("blocked",))
    monkeypatch.setattr(
        cli,
        "SOURCES",
        {"reachable": type("R", (_RecordingSource,), {"name": "reachable"}),
         "blocked": type("B", (_RecordingSource,), {"name": "blocked"})},
    )
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {
            "reachable": {"models": ["model_y"], "countries": ["DE"]},
            "blocked": {"models": ["model_y"], "countries": ["HU"]},
        },
    )

    cli.cmd_scrape_local(argparse.Namespace(max_pages=None))

    assert attempted == ["blocked"]


def test_scheduled_run_never_retires_what_the_local_run_collected(isolated_db, monkeypatch):
    """The two runs write to one database on different schedules. Neither
    may retire the other's listings merely by not having looked at them -
    that would make each run silently delete the other's work."""
    _seed_one_listing(isolated_db, source="blocked", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "DATACENTER_BLOCKED_SOURCES", ("blocked",))
    monkeypatch.setattr(cli, "SOURCES", {"reachable": _FakeOkSource, "blocked": _FakeOkSource})
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {
            "reachable": {"models": ["model_y"], "countries": ["DE"]},
            "blocked": {"models": ["model_y"], "countries": ["HU"]},
        },
    )

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=False))

    assert _is_active(isolated_db, "blocked:old") is True


def test_scrape_targets_only_reference_real_sources_and_models():
    assert set(cli.SCRAPE_TARGETS) == set(cli.SOURCES)
    for target in cli.SCRAPE_TARGETS.values():
        assert set(target["models"]) <= set(cli.MODELS)
        assert target["countries"], "every source must scrape at least one country"


def test_export_drops_entries_too_cheap_to_be_a_car(isolated_db, tmp_path):
    """Marketplaces list referral links and deposits alongside cars. A real
    1 EUR "Tesla Empfehlungslink" entered the median price, the trend fit and
    the depreciation curve before this filter existed."""
    seen_at = datetime(2026, 8, 28)
    with session_scope(get_engine(isolated_db)) as session:
        for listing_id, price in (("junk:1", 1.0), ("real:1", 30_000.0)):
            session.add(
                Listing(
                    id=listing_id,
                    source="kleinanzeigen",
                    source_listing_id=listing_id,
                    model="model_y",
                    country="DE",
                    url="https://example.com",
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                    is_active=True,
                )
            )
            session.add(
                ListingSnapshot(
                    listing_id=listing_id,
                    observed_at=seen_at,
                    price_original=price,
                    currency_original="EUR",
                    price_eur=price,
                    mileage_km=50_000,
                )
            )

    out = tmp_path / "listings.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    exported = {l["id"] for l in json.loads(out.read_text(encoding="utf-8"))["listings"]}
    assert exported == {"real:1"}


# --- partial results & the retirement cap --------------------------------


class _FakePartialSource(Source):
    """A source that fetched some pages and then hit a wall.

    The real shape of this: autoscout24/model_y/IT answered 502 on page 13
    of a live run. Twelve pages of good listings were in hand; the rest of
    the market was simply never looked at.
    """

    name = "fake_ok"

    def __enter__(self) -> "_FakePartialSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        raise PartialResults(
            [
                RawListing(
                    source="fake_ok",
                    source_listing_id=f"{model}-{country}",
                    model=model,
                    country=country,
                    url="https://example.com/1",
                    price_original=30_000,
                    currency_original="EUR",
                )
            ],
            "page 13 failed (HTTPStatusError: 502)",
        )


def test_a_partial_combo_still_stores_what_it_managed_to_fetch(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakePartialSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))  # not a failure: real data arrived

    with session_scope(get_engine(isolated_db)) as session:
        stored = [listing.id for listing in session.execute(select(Listing)).scalars()]
    assert stored == ["fake_ok:model_y-DE"]


def test_a_partial_combo_never_retires_the_listings_it_did_not_get_to(isolated_db, monkeypatch):
    """The whole point of PartialResults. Pages 13+ were never fetched, so
    the cars listed on them were not seen - and "not seen" is only evidence
    of a sale when the whole market was actually looked at."""
    _seed_one_listing(isolated_db, source="fake_ok", seen_at=datetime(2026, 1, 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakePartialSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _is_active(isolated_db, "fake_ok:old") is True


def test_a_partial_combo_does_not_fail_the_run(isolated_db, monkeypatch, capsys):
    """It stored real, current prices - failing the whole nightly run over a
    missing tail would just train everyone to ignore a red build. It is
    still reported, because a source that is quietly always partial is a
    problem worth seeing."""
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakePartialSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    output = capsys.readouterr().out
    assert "partial fake_ok/model_y/DE" in output
    assert "page 13 failed" in output


def _seed_listings(db_url: str, *, source: str, count: int, seen_at) -> None:
    with session_scope(get_engine(db_url)) as session:
        for i in range(count):
            session.add(
                Listing(
                    id=f"{source}:old-{i}",
                    source=source,
                    source_listing_id=f"old-{i}",
                    model="model_y",
                    country="DE",
                    url=f"https://example.com/old-{i}",
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                    is_active=True,
                )
            )


def _active_count(db_url: str, source: str) -> int:
    with session_scope(get_engine(db_url)) as session:
        return len(
            list(
                session.execute(
                    select(Listing.id).where(Listing.source == source, Listing.is_active.is_(True))
                ).scalars()
            )
        )


def test_an_implausibly_large_retirement_is_refused_even_when_the_combo_reported_success(
    isolated_db, monkeypatch, capsys
):
    """The quiet failure mode: a throttle page served as HTTP 200 with no
    ads on it looks exactly like a successful scrape of an empty market. No
    guard keyed on a source *reporting* trouble can catch that, so this one
    keys on the claim itself - forty cars do not sell overnight."""
    # Seen yesterday: this is a scrape that broke *today*, which is what the
    # cap is for. Listings already stale for a week are a different question,
    # answered by STALE_AFTER_DAYS below.
    _seed_listings(isolated_db, source="fake_ok", count=40, seen_at=utc_now() - timedelta(days=1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _active_count(isolated_db, "fake_ok") == 41, "the seeded 40 must survive, plus the one just seen"
    assert "refusing" in capsys.readouterr().out


def test_an_ordinary_days_worth_of_sales_still_retires(isolated_db, monkeypatch):
    """The cap must not become a way of never retiring anything: a normal
    run, where most listings are seen again and a few are not, retires."""
    _seed_listings(isolated_db, source="fake_ok", count=40, seen_at=utc_now() - timedelta(days=1))

    class _SeesMostOfThem(_FakeOkSource):
        def fetch_listings(self, *, model, country, max_pages=None):
            return [
                RawListing(
                    source="fake_ok",
                    source_listing_id=f"old-{i}",
                    model=model,
                    country=country,
                    url=f"https://example.com/old-{i}",
                    price_original=30_000,
                    currency_original="EUR",
                )
                for i in range(37)  # three of the forty are gone
            ]

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _SeesMostOfThem})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _active_count(isolated_db, "fake_ok") == 37


def test_the_cap_does_not_apply_to_a_source_with_only_a_handful_of_listings(isolated_db, monkeypatch):
    """A market with three cars in it can legitimately lose two in a day -
    percentages only mean something once there are enough listings."""
    _seed_listings(isolated_db, source="fake_ok", count=3, seen_at=utc_now() - timedelta(days=1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _active_count(isolated_db, "fake_ok") == 1, "only the listing this run saw"


# --- re-scraping an already-known listing --------------------------------


def test_a_rescrape_backfills_fields_that_were_missing_when_the_listing_was_first_stored(
    isolated_db, monkeypatch
):
    """Regression, and a bad one: a listing was only ever written in full on
    first sight, so a field that was missing then stayed missing forever. A
    whole run of Tesla listings read "Untitled" in the dashboard long after
    the source had been fixed to produce titles, because those listings were
    already known and re-scraping them never touched the column."""
    with session_scope(get_engine(isolated_db)) as session:
        session.add(
            Listing(
                id="fake_ok:model_y-DE",
                source="fake_ok",
                source_listing_id="model_y-DE",
                model="model_y",
                country="DE",
                url="https://example.com/1",
                title_raw=None,
                photo_urls=[],
                first_seen_at=datetime(2026, 1, 1),
                last_seen_at=datetime(2026, 1, 1),
                is_active=True,
            )
        )

    class _NowWithTitleAndPhotos(_FakeOkSource):
        def fetch_listings(self, *, model, country, max_pages=None):
            return [
                RawListing(
                    source="fake_ok",
                    source_listing_id=f"{model}-{country}",
                    model=model,
                    country=country,
                    url="https://example.com/1",
                    price_original=30_000,
                    currency_original="EUR",
                    title_raw="Model Y · Long Range AWD · 2022",
                    photo_urls=["https://example.com/photo.jpg"],
                    location="Berlin",
                )
            ]

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _NowWithTitleAndPhotos})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    with session_scope(get_engine(isolated_db)) as session:
        listing = session.get(Listing, "fake_ok:model_y-DE")
        assert listing.title_raw == "Model Y · Long Range AWD · 2022"
        assert listing.photo_urls == ["https://example.com/photo.jpg"]
        assert listing.location == "Berlin"


def test_a_thin_rescrape_does_not_blank_out_details_already_held(isolated_db, monkeypatch):
    """The other half of the same rule: refreshing must never be a way to
    lose data. A source that returns a listing with no photos this time
    (a slow image CDN, a trimmed response) keeps the ones it gave before."""
    with session_scope(get_engine(isolated_db)) as session:
        session.add(
            Listing(
                id="fake_ok:model_y-DE",
                source="fake_ok",
                source_listing_id="model_y-DE",
                model="model_y",
                country="DE",
                url="https://example.com/1",
                title_raw="A good title",
                photo_urls=["https://example.com/known.jpg"],
                location="Berlin",
                first_seen_at=datetime(2026, 1, 1),
                last_seen_at=datetime(2026, 1, 1),
                is_active=True,
            )
        )

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})  # returns no title, no photos
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    with session_scope(get_engine(isolated_db)) as session:
        listing = session.get(Listing, "fake_ok:model_y-DE")
        assert listing.title_raw == "A good title"
        assert listing.photo_urls == ["https://example.com/known.jpg"]
        assert listing.location == "Berlin"


# --- the forint rate the dashboard converts with -------------------------


def test_the_export_carries_the_rate_the_run_actually_used(isolated_db, tmp_path, monkeypatch):
    """Prices are stored in euros because the market spans six eurozone
    countries; the person reading the dashboard shops in Hungary. The rate
    travels with the export so a listing never carries a converted copy of
    its own price that would go stale the moment the rate moved."""
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0027413}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})
    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    out = tmp_path / "listings.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    payload = json.loads(out.read_text())

    # Stored as "1 HUF = x EUR"; the dashboard wants forints per euro.
    assert payload["hufPerEur"] == pytest.approx(1 / 0.0027413, rel=1e-3)


def test_the_export_says_so_rather_than_guessing_when_no_rate_was_ever_stored(isolated_db, tmp_path):
    """A fresh database has no rate. Inventing one would put wrong forint
    figures on every card; null lets the dashboard stay in euros."""
    out = tmp_path / "listings.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    assert json.loads(out.read_text())["hufPerEur"] is None


def test_storing_the_same_days_rate_twice_updates_it_rather_than_failing(isolated_db):
    """Two runs on one day (the scheduled one and scrape-local) both store
    rates, and (rate_date, currency) is the primary key."""
    cli._store_rates(date(2026, 8, 28), {"HUF": 0.0027})
    cli._store_rates(date(2026, 8, 28), {"HUF": 0.0028})  # must not raise

    with session_scope(get_engine(isolated_db)) as session:
        assert cli._latest_huf_per_eur(session) == pytest.approx(1 / 0.0028, rel=1e-3)


def test_the_cap_delays_retirement_rather_than_vetoing_it_forever(isolated_db, monkeypatch):
    """The cap refuses the same implausible gap every day, so on its own it
    is permanent, not a delay: a source that really did shrink - or a
    country this project stopped scraping - would keep its dead listings on
    the dashboard for good. Measured before this backstop existed: ten runs
    against a market that fell from 400 cars to 20 retired nothing at all.

    A week of nobody finding a listing settles it either way. Either the car
    is gone, or the source has been broken all week and its prices are a
    week stale - and a week-old price shown as today's is its own kind of
    wrong."""
    _seed_listings(isolated_db, source="fake_ok", count=40, seen_at=utc_now() - timedelta(days=cli.STALE_AFTER_DAYS + 1))

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})  # sees 1 of the 41
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert _active_count(isolated_db, "fake_ok") == 1, "week-old listings go even when the cap says the gap is implausible"


def test_the_backstop_does_not_fire_on_a_source_that_broke_today(isolated_db, monkeypatch, capsys):
    """The other half: one bad day must still cost nothing. Only the part
    that is genuinely a week stale is retired, not everything unseen."""
    _seed_listings(isolated_db, source="fake_ok", count=30, seen_at=utc_now() - timedelta(days=1))
    with session_scope(get_engine(isolated_db)) as session:
        for i in range(30, 34):  # four that have been missing for over a week
            session.add(
                Listing(
                    id=f"fake_ok:old-{i}",
                    source="fake_ok",
                    source_listing_id=f"old-{i}",
                    model="model_y",
                    country="DE",
                    url=f"https://example.com/old-{i}",
                    first_seen_at=utc_now() - timedelta(days=30),
                    last_seen_at=utc_now() - timedelta(days=cli.STALE_AFTER_DAYS + 2),
                    is_active=True,
                )
            )

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    # 34 seeded + 1 just seen = 35 active; only the 4 week-old ones go.
    assert _active_count(isolated_db, "fake_ok") == 31
    assert "refusing" in capsys.readouterr().out, "and it still says the gap looked wrong"
