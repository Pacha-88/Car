"""cli.py's orchestration logic: rate resolution and the scrape-all
daily-cron entry point. Uses a real (temp-file) SQLite engine via
DATABASE_URL, same pattern as test_timeutil.py, rather than mocking the DB
layer away - the thing worth proving is that storage actually happens
through cmd_scrape_all's real code path, not just that it calls functions.
"""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from car_tracker import cli
from car_tracker.db.models import FxRate, Listing, ListingSnapshot
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

    cli.cmd_scrape_local(argparse.Namespace(max_pages=None, source=None))

    assert attempted == ["blocked"]


def test_scrape_local_can_be_narrowed_to_one_source(isolated_db, monkeypatch):
    """The wrapper retries a hard block through the person's own Chrome.

    Without this it re-ran everything: the source that had just succeeded,
    and the six hundred Hungarian pages that had just been fetched - more
    requests at exactly the moment a site has started refusing them.
    """
    attempted: list[str] = []

    class _RecordingSource(_FakeOkSource):
        def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None):
            attempted.append(self.name)
            return []

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "DATACENTER_BLOCKED_SOURCES", ("one", "two"))
    monkeypatch.setattr(
        cli,
        "SOURCES",
        {"one": type("A", (_RecordingSource,), {"name": "one"}),
         "two": type("B", (_RecordingSource,), {"name": "two"})},
    )
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {"one": {"models": ["model_y"], "countries": ["DE"]},
         "two": {"models": ["model_y"], "countries": ["HU"]}},
    )

    cli.cmd_scrape_local(argparse.Namespace(max_pages=None, source=["two"]))
    assert attempted == ["two"]


def test_scrape_local_refuses_a_source_that_is_not_its_own(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "DATACENTER_BLOCKED_SOURCES", ("one",))
    with pytest.raises(SystemExit, match="belongs to scrape-all"):
        cli.cmd_scrape_local(argparse.Namespace(max_pages=None, source=["autoscout24"]))


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


def test_the_export_carries_the_sellers_own_number_beside_the_euro_one(isolated_db, tmp_path, monkeypatch):
    """A forint price shown to a Hungarian buyer must be the one on the ad.

    Euros are the unit of record - the market spans six eurozone countries -
    but that makes a Hungarian car's displayed price a round trip: converted
    at the rate of the day it was scraped, converted back at the rate of the
    day it was exported. Those are the same day for the scheduled sources.
    Használtautó is scraped by hand, so its listings routinely carry a rate
    days or weeks old, and the card then disagrees with the ad it links to.
    """
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0027413}))

    class _HungarianSource(_FakeOkSource):
        def fetch_listings(self, *, model, country, max_pages=None):
            return [
                RawListing(
                    source="fake_hu",
                    source_listing_id="1",
                    model=model,
                    country="HU",
                    url="https://example.invalid/1",
                    price_original=10_390_000.0,
                    currency_original="HUF",
                    mileage_km=136_000,
                    model_year=2023,
                    first_registration=date(2023, 1, 1),
                    variant="RWD",
                    title_raw="TESLA MODEL Y RWD",
                    photo_urls=[],
                    seller_type="private",
                    location=None,
                    power_kw=220,
                )
            ]

    monkeypatch.setattr(cli, "SOURCES", {"fake_hu": _HungarianSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_hu": {"models": ["model_y"], "countries": ["HU"]}})
    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    out = tmp_path / "listings.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    listing = json.loads(out.read_text())["listings"][0]

    assert listing["priceOriginal"] == 10_390_000.0
    assert listing["currencyOriginal"] == "HUF"
    # And the euro figure is still there for everything derived from it.
    assert listing["priceEur"] == pytest.approx(10_390_000 * 0.0027413)


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


def test_storing_rates_survives_the_other_run_writing_them_first(isolated_db, monkeypatch):
    """The scheduled GitHub run and the scrape-local cron both aim at the
    same morning and the same database, and store the *same* ECB numbers
    under the same (date, currency) key. Asking "does this row exist yet"
    before either has committed sends both down the insert path, and one
    into a duplicate-key error. Measured with two runs started together:
    11 collisions in 12 attempts."""
    real_scope = cli.session_scope
    state = {"attempts": 0, "raced": False}

    class _RacingSession:
        """A session that lets the other run commit *after* our read - which
        is the only ordering that produces the collision. Committing before
        it just means we find the row and take the update path."""

        def __init__(self, inner):
            self._inner = inner

        def get(self, *args, **kwargs):
            found = self._inner.get(*args, **kwargs)
            if not state["raced"]:
                state["raced"] = True
                with real_scope() as other:  # the other run, committing now
                    for currency in ("HUF", "USD"):
                        other.add(FxRate(rate_date=date(2026, 8, 28), currency=currency, rate_to_eur=0.001))
            return found

        def __getattr__(self, name):
            return getattr(self._inner, name)

    @contextmanager
    def racing_scope(*args, **kwargs):
        state["attempts"] += 1
        with real_scope(*args, **kwargs) as session:
            yield _RacingSession(session) if state["attempts"] == 1 else session

    monkeypatch.setattr(cli, "session_scope", racing_scope)
    cli._store_rates(date(2026, 8, 28), {"HUF": 0.0028, "USD": 0.92})
    monkeypatch.undo()

    assert state["attempts"] == 2, "the first attempt must have collided and been retried"
    with session_scope(get_engine(isolated_db)) as session:
        assert cli._latest_huf_per_eur(session) == pytest.approx(1 / 0.0028, rel=1e-3), (
            "and the retry must land this run's value, not the one it collided with"
        )


def test_a_run_still_scrapes_when_the_rates_cannot_be_stored(isolated_db, monkeypatch, capsys):
    """Storing the rates only lets the *export* convert to forints later.
    Losing that is one number falling back to euros - not a reason to throw
    away a morning's prices before a single car has been fetched."""
    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "_store_rates", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db said no")))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))  # must not raise

    output = capsys.readouterr().out
    assert "could not store fx rates" in output
    with session_scope(get_engine(isolated_db)) as session:
        assert session.get(Listing, "fake_ok:model_y-DE") is not None, "the cars still got stored"


def test_a_rescrape_clears_a_registration_date_that_cannot_be_true(isolated_db, monkeypatch):
    """The refresh rule is `or` for most fields so a thin response can't
    blank good data - but that would also preserve a bad date forever,
    since the sanitised value is None. When the source does say something
    about the date, its answer wins, including "not believable"."""
    with session_scope(get_engine(isolated_db)) as session:
        session.add(
            Listing(
                id="fake_ok:model_y-DE",
                source="fake_ok",
                source_listing_id="model_y-DE",
                model="model_y",
                country="DE",
                url="https://example.com/1",
                model_year=2002,
                first_registration=date(2002, 12, 1),
                first_seen_at=utc_now(),
                last_seen_at=utc_now(),
                is_active=True,
            )
        )

    class _StillSaysTwoThousandTwo(_FakeOkSource):
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
                    model_year=2002,
                    first_registration=date(2002, 12, 1),
                )
            ]

    monkeypatch.setattr(cli, "fetch_latest_rates", lambda: (date(2026, 8, 28), {"HUF": 0.0025}))
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _StillSaysTwoThousandTwo})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_ok": {"models": ["model_y"], "countries": ["DE"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    with session_scope(get_engine(isolated_db)) as session:
        listing = session.get(Listing, "fake_ok:model_y-DE")
        assert listing.first_registration is None
        assert listing.model_year is None


def _ecb_down():
    raise RuntimeError("ecb.europa.eu timed out")


class _FakeHufSource(Source):
    """A Hungarian listing priced in forints - needs a HUF rate to store."""

    name = "fake_hu"

    def __enter__(self) -> "_FakeHufSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch_listings(self, *, model: str, country: str, max_pages: int | None = None) -> list[RawListing]:
        return [
            RawListing(
                source="fake_hu",
                source_listing_id=f"{model}-{country}",
                model=model,
                country=country,
                url="https://example.hu/1",
                price_original=14_500_000,
                currency_original="HUF",
            )
        ]


def test_ecb_downtime_falls_back_to_the_stored_rates(isolated_db, monkeypatch, capsys):
    """One ECB timeout used to kill the entire nightly run before a single
    car was fetched - even though the fx_rates table already held the last
    run's numbers, and daily reference rates move fractions of a percent."""
    cli._store_rates(date(2026, 8, 28), {"HUF": 0.0027413})

    monkeypatch.setattr(cli, "fetch_latest_rates", _ecb_down)
    monkeypatch.setattr(cli, "SOURCES", {"fake_hu": _FakeHufSource})
    monkeypatch.setattr(cli, "SCRAPE_TARGETS", {"fake_hu": {"models": ["model_y"], "countries": ["HU"]}})

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))  # must not raise

    assert "using stored rates from 2026-08-28" in capsys.readouterr().out
    with session_scope(get_engine(isolated_db)) as session:
        snap = session.execute(select(ListingSnapshot)).scalars().one()
        assert snap.price_eur == pytest.approx(14_500_000 * 0.0027413)


def test_ecb_downtime_with_no_stored_rates_still_scrapes_the_eur_markets(isolated_db, monkeypatch):
    """Nearly every listing is EUR-priced and needs no rate at all. The one
    combo that genuinely cannot convert fails inside its own try - marked
    failed, exempt from retirement - instead of taking the run with it."""
    monkeypatch.setattr(cli, "fetch_latest_rates", _ecb_down)
    monkeypatch.setattr(cli, "SOURCES", {"fake_ok": _FakeOkSource, "fake_hu": _FakeHufSource})
    monkeypatch.setattr(
        cli,
        "SCRAPE_TARGETS",
        {
            "fake_ok": {"models": ["model_y"], "countries": ["DE"]},
            "fake_hu": {"models": ["model_y"], "countries": ["HU"]},
        },
    )
    _seed_one_listing(isolated_db, source="fake_hu", seen_at=utc_now() - timedelta(days=1))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_scrape_all(argparse.Namespace(max_pages=None, include_blocked=True))

    assert "fake_hu/model_y/HU" in str(exc_info.value)
    with session_scope(get_engine(isolated_db)) as session:
        stored = {listing.id for listing in session.execute(select(Listing)).scalars()}
    assert "fake_ok:model_y-DE" in stored, "the EUR market must still have been scraped and stored"
    assert _is_active(isolated_db, "fake_hu:old") is True, "the failed HUF source retires nothing"


# --- batched storage ------------------------------------------------------
# The nightly run stores ~3.200 listings into a Supabase an ocean away from
# the runner. One SELECT per listing plus row-at-a-time writes meant ~1.200
# statements per 400-listing combo (measured on real Postgres through
# PgBouncer); the batch path does the same work in 3. At ~100ms per round
# trip that was the difference between a 20-minute scrape step and a
# 6-minute one.


def _raw(i: int, *, price: float = 30_000) -> RawListing:
    return RawListing(
        source="fake_ok",
        source_listing_id=f"car-{i}",
        model="model_y",
        country="DE",
        url=f"https://example.com/{i}",
        price_original=price,
        currency_original="EUR",
        mileage_km=50_000 + i,
        model_year=2023,
        title_raw=f"Car {i}",
        photo_urls=[f"https://img/{i}.jpg"],
    )


def test_the_batch_path_stores_exactly_what_the_row_at_a_time_path_stores(isolated_db):
    rates = {"EUR": 1.0}
    now = utc_now()
    with session_scope(get_engine(isolated_db)) as session:
        for i in range(30):
            cli._upsert(session, _raw(i), rates_to_eur=rates, observed_at=now)

    import os

    db2 = f"{isolated_db.removesuffix('.db')}-batch.db"
    os.environ["DATABASE_URL"] = db2
    init_db(get_engine(db2))
    cli._store_batch([_raw(i) for i in range(30)], rates_to_eur=rates, observed_at=now)

    def dump(url):
        with session_scope(get_engine(url)) as session:
            return sorted(
                (l.id, l.title_raw, tuple(l.photo_urls), l.model_year, l.last_seen_at, l.is_active)
                for l in session.execute(select(Listing)).scalars()
            )

    os.environ["DATABASE_URL"] = isolated_db
    assert dump(isolated_db) == dump(db2)


def test_the_same_car_twice_in_one_combo_updates_one_row_instead_of_colliding(isolated_db):
    """Pages shift underneath a paginated scrape, so one combo can hand the
    same listing back twice. The prefetch cache must catch the row this run
    just created, or the second occurrence is a duplicate-key insert."""
    twice = [_raw(1, price=30_000), _raw(1, price=29_500)]
    cli._store_batch(twice, rates_to_eur={"EUR": 1.0}, observed_at=utc_now())

    with session_scope(get_engine(isolated_db)) as session:
        rows = list(session.execute(select(Listing)).scalars())
        snaps = list(session.execute(select(ListingSnapshot)).scalars())
    assert len(rows) == 1
    assert len(snaps) == 2, "both sightings still record a snapshot"


def test_export_titles_rows_stored_before_the_never_empty_guarantee(isolated_db, tmp_path):
    """Old rows only repair in the DB when their site serves them again -
    and the datacenter-blocked sources may wait days for a scrape-local
    run. The export is the last line: no JSON ships an empty title."""
    with session_scope(get_engine(isolated_db)) as session:
        session.add(
            Listing(
                id="tesla:VIN1",
                source="tesla",
                source_listing_id="VIN1",
                model="model_y",
                country="DE",
                url="https://example.com/1",
                title_raw=None,
                first_seen_at=utc_now(),
                last_seen_at=utc_now(),
                is_active=True,
            )
        )
        session.add(
            ListingSnapshot(
                listing_id="tesla:VIN1",
                observed_at=utc_now(),
                price_original=30_000,
                currency_original="EUR",
                price_eur=30_000,
                mileage_km=10_000,
            )
        )

    out = tmp_path / "out.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    payload = json.loads(out.read_text())
    assert payload["listings"][0]["titleRaw"] == "Tesla Model Y"
