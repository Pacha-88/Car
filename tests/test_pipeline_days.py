"""Five days of the real pipeline, end to end.

Every other test exercises one layer; the dashboard's numbers come out of
their interaction - _upsert stamping last_seen_at, _retire_unseen reading
it, price_points compressing what _store_batch wrote, the export deriving
badges and histories from all of it. This walks five scripted days through
those actual code paths (no hand-written SQL) and then checks the export
says exactly what happened:

  anchors  30 cars listed day 0, never repriced, never sold
  cutter   listed day 0 at 40.000, cut to 38.000 on day 2
  sold     listed day 0, gone from day 3's scrape (retired that day)
  blip     listed day 0; day 2's scrape misread its price as zero
  arrival  first seen on day 4, the newest scrape
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time as dtime, timedelta

import pytest

from car_tracker import cli
from car_tracker.db.session import get_engine, init_db, session_scope
from car_tracker.sources.base import RawListing
from car_tracker.timeutil import utc_now


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/pipeline.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    init_db(get_engine(db_url))
    return db_url


def _raw(listing_id: str, price: float, *, title="Long Range AWD") -> RawListing:
    return RawListing(
        source="autoscout24",
        source_listing_id=listing_id,
        model="model_y",
        country="DE",
        url=f"https://example.test/{listing_id}",
        price_original=price,
        currency_original="EUR",
        mileage_km=50_000,
        model_year=2023,
        title_raw=title,
        photo_urls=[],
    )


def test_five_days_of_the_real_pipeline(isolated_db, tmp_path):
    today = utc_now().date()
    def at(day: int) -> datetime:
        # Day 4 = today, "scraped" at midnight: with any later hour the
        # days-at-current-price asserts would only hold for test runs
        # after that hour of the day - a test green at 10:00 UTC and red
        # in a 07:31 CI run. Midnight makes (now - at(n)).days exact
        # whatever the clock says.
        return datetime.combine(today - timedelta(days=4 - day), dtime(0, 0))

    anchors = [f"anchor{i}" for i in range(30)]
    targets = {"autoscout24": {"models": ["model_y"], "countries": ["DE"]}}

    def market(day: int) -> list[RawListing]:
        cars = [_raw(a, 30_000 + 100 * i) for i, a in enumerate(anchors)]
        cars.append(_raw("cutter", 40_000.0 if day < 2 else 38_000.0))
        if day < 3:
            cars.append(_raw("sold", 35_000.0))
        blip_price = 0.0 if day == 2 else 41_000.0
        cars.append(_raw("blip", blip_price))
        if day == 4:
            cars.append(_raw("arrival", 39_000.0))
        return cars

    for day in range(5):
        cli._store_batch(market(day), rates_to_eur={"EUR": 1.0}, observed_at=at(day))
        cli._retire_unseen(at(day), sources=targets, skip_sources=set())

    out = tmp_path / "listings.json"
    cli.cmd_export(argparse.Namespace(out=str(out)))
    payload = json.loads(out.read_text())
    by_id = {l["id"].removeprefix("autoscout24:"): l for l in payload["listings"]}

    # The sold car is retired, everything else is on the dashboard.
    assert "sold" not in by_id
    assert set(by_id) == {*anchors, "cutter", "blip", "arrival"}

    # The cutter's history is exactly the two prices its seller set.
    cutter = by_id["cutter"]
    assert cutter["priceHistory"] == [
        [at(0).date().isoformat(), 40_000.0, 40_000.0],
        [at(2).date().isoformat(), 38_000.0, 38_000.0],
    ]
    assert cutter["priceEur"] == 38_000.0
    assert cutter["daysAtCurrentPrice"] == 2  # since day 2, scraped daily

    # One misread price neither erases the blip car nor becomes a "cut".
    blip = by_id["blip"]
    assert blip["priceEur"] == 41_000.0
    assert [p[1] for p in blip["priceHistory"]] == [41_000.0]
    assert blip["daysAtCurrentPrice"] == 4

    # Only the day-4 arrival is new.
    assert blip["isNew"] is False and cutter["isNew"] is False
    assert by_id["arrival"]["isNew"] is True

    # Market history: five days, and the sold car counts while it lasted.
    days = [d for d in payload["marketHistory"] if d["model"] == "model_y"]
    assert [d["date"] for d in days] == [at(i).date().isoformat() for i in range(5)]
    assert days[0]["n"] == 33  # 30 anchors + cutter + sold + blip
    assert days[3]["n"] == 32  # the sold car is out; the blip is back

    # The index moved exactly once: day 2, by the cutter's 5% cut averaged
    # over the matched pairs (the blip's zero is a gap, not a ratio).
    assert days[1]["index"] == pytest.approx(100.0)
    assert days[2]["index"] < 100.0
    assert days[3]["index"] == pytest.approx(days[2]["index"])

    # The sale-time cohort is honestly empty: the one sale was on the
    # market the day tracking began, so its true span is unknowable.
    assert payload["saleTimes"] == []

    # And the scrape moment matches the last scripted day.
    assert payload["latestScrapeAt"] == at(4).isoformat() + "Z"
