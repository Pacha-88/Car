"""Regression test for a real bug hit while building cli.py's export
command: SQLite doesn't round-trip tzinfo, so a ListingSnapshot.observed_at
written as timezone-aware comes back naive after going through a real
engine — comparing it against a fresh datetime.now(timezone.utc) raised
TypeError: can't subtract offset-naive and offset-aware datetimes. Fixed by
standardizing on naive UTC everywhere (see timeutil.py); this test exercises
the actual round-trip rather than only unit-testing days_at_current_price
in isolation, which didn't catch it (both of its own datetimes were
consistently timezone-aware).
"""

from __future__ import annotations

from sqlalchemy import select

from car_tracker.analysis.listing_status import days_at_current_price
from car_tracker.db.models import Listing, ListingSnapshot
from car_tracker.db.session import get_engine, init_db, session_scope
from car_tracker.timeutil import utc_now


def test_days_at_current_price_after_real_sqlite_round_trip(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path}/regression.db")
    init_db(engine)

    observed_at = utc_now()
    with session_scope(engine) as session:
        session.add(
            Listing(
                id="test:1",
                source="test",
                source_listing_id="1",
                model="model_y",
                country="DE",
                url="https://example.com",
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
        )
        session.add(
            ListingSnapshot(
                listing_id="test:1",
                observed_at=observed_at,
                price_original=40_000,
                currency_original="EUR",
                price_eur=40_000,
                mileage_km=50_000,
            )
        )

    with session_scope(engine) as session:
        snapshots = list(session.execute(select(ListingSnapshot)).scalars())
        # This is the actual regression: utc_now() must not raise when
        # subtracted from a snapshot's DB-retrieved observed_at.
        assert days_at_current_price(snapshots, as_of=utc_now()) == 0
