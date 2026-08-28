"""cli.py's orchestration logic: rate resolution and the scrape-all
daily-cron entry point. Uses a real (temp-file) SQLite engine via
DATABASE_URL, same pattern as test_timeutil.py, rather than mocking the DB
layer away - the thing worth proving is that storage actually happens
through cmd_scrape_all's real code path, not just that it calls functions.
"""

from __future__ import annotations

import argparse
from datetime import date

import pytest
from sqlalchemy import select

from car_tracker import cli
from car_tracker.db.models import Listing
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
        cli.cmd_scrape_all(argparse.Namespace(max_pages=None))

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

    cli.cmd_scrape_all(argparse.Namespace(max_pages=None))  # must not raise

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


def test_scrape_targets_only_reference_real_sources_and_models():
    assert set(cli.SCRAPE_TARGETS) == set(cli.SOURCES)
    for target in cli.SCRAPE_TARGETS.values():
        assert set(target["models"]) <= set(cli.MODELS)
        assert target["countries"], "every source must scrape at least one country"
