from datetime import date, datetime, timezone

import pytest

from car_tracker.analysis.listing_status import days_at_current_price, is_new_since_last_scrape
from car_tracker.db.models import ListingSnapshot


def _snap(days_ago: int, price: float) -> ListingSnapshot:
    return ListingSnapshot(
        observed_at=datetime(2026, 1, 10, tzinfo=timezone.utc).replace(day=10 - days_ago),
        price_original=price,
        currency_original="EUR",
        price_eur=price,
        mileage_km=50_000,
    )


AS_OF = datetime(2026, 1, 10, tzinfo=timezone.utc)


def test_price_unchanged_across_all_snapshots():
    snapshots = [_snap(6, 40_000), _snap(4, 40_000), _snap(2, 40_000), _snap(0, 40_000)]
    assert days_at_current_price(snapshots, as_of=AS_OF) == 6


def test_price_dropped_once():
    snapshots = [_snap(6, 41_000), _snap(4, 41_000), _snap(2, 40_000), _snap(0, 40_000)]
    assert days_at_current_price(snapshots, as_of=AS_OF) == 2


def test_single_snapshot_held_since_it_was_first_seen():
    assert days_at_current_price([_snap(3, 40_000)], as_of=AS_OF) == 3


def test_unsorted_snapshots_still_work():
    snapshots = [_snap(0, 40_000), _snap(6, 41_000), _snap(2, 40_000), _snap(4, 41_000)]
    assert days_at_current_price(snapshots, as_of=AS_OF) == 2


def test_empty_snapshots_raises():
    with pytest.raises(ValueError):
        days_at_current_price([], as_of=AS_OF)


def test_new_since_last_scrape_matches_latest_date():
    first_seen = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
    assert is_new_since_last_scrape(first_seen, latest_scrape_date=date(2026, 1, 10)) is True


def test_not_new_when_first_seen_before_latest_scrape():
    first_seen = datetime(2026, 1, 9, 9, 0, tzinfo=timezone.utc)
    assert is_new_since_last_scrape(first_seen, latest_scrape_date=date(2026, 1, 10)) is False


def _huf_snap(days_ago: int, price_ft: float, rate: float) -> ListingSnapshot:
    return ListingSnapshot(
        observed_at=datetime(2026, 1, 10, tzinfo=timezone.utc).replace(day=10 - days_ago),
        price_original=price_ft,
        currency_original="HUF",
        price_eur=price_ft * rate,
        mileage_km=50_000,
    )


def test_a_steady_forint_price_is_not_broken_by_the_daily_fx_rate():
    """price_eur is derived with the day's ECB rate, so for a HUF-priced
    listing it drifts a little every day the rate moves. Comparing it made
    every Használtautó listing read "at this price for 0 days" forever,
    however long the seller had actually held the price. What "unchanged"
    means is the seller's own number."""
    snapshots = [
        _huf_snap(6, 14_500_000, 0.0027413),
        _huf_snap(4, 14_500_000, 0.0027389),  # rate moved, seller didn't
        _huf_snap(2, 14_500_000, 0.0027441),
        _huf_snap(0, 14_500_000, 0.0027402),
    ]
    assert days_at_current_price(snapshots, as_of=AS_OF) == 6


def test_a_genuine_forint_price_drop_still_resets_the_clock():
    snapshots = [
        _huf_snap(6, 14_900_000, 0.0027413),
        _huf_snap(2, 14_500_000, 0.0027441),
        _huf_snap(0, 14_500_000, 0.0027402),
    ]
    assert days_at_current_price(snapshots, as_of=AS_OF) == 2
