"""cli.py's orchestration logic: rate resolution and the scrape-all
daily-cron entry point. Uses a real (temp-file) SQLite engine via
DATABASE_URL, same pattern as test_timeutil.py, rather than mocking the DB
layer away - the thing worth proving is that storage actually happens
through cmd_scrape_all's real code path, not just that it calls functions.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

from car_tracker import cli
from car_tracker.db.models import Listing, ListingSnapshot
from car_tracker.db.session import get_engine, init_db, session_scope
from car_tracker.sources.base import RawListing, Source


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
