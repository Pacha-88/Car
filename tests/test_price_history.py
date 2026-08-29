"""analysis/price_history.py - one car's price over time, and the market's."""

from datetime import date, datetime

import pytest

from car_tracker.analysis.price_history import market_history, price_points
from car_tracker.db.models import ListingSnapshot


def _snap(listing_id, day, eur, original=None, currency="EUR"):
    return ListingSnapshot(
        listing_id=listing_id,
        observed_at=datetime(2026, 8, day, 6, 0),
        price_original=original if original is not None else eur,
        currency_original=currency,
        price_eur=eur,
        mileage_km=1000,
    )


# --- one car ---------------------------------------------------------------


def test_only_the_days_the_price_actually_changed_are_kept():
    """A daily scrape writes a snapshot a day; a car listed a month has
    thirty of them and one or two prices."""
    snaps = [_snap("a", d, 40000.0) for d in range(1, 8)] + [_snap("a", d, 38000.0) for d in range(8, 15)]
    points = price_points(snaps)
    assert [(p.on, p.price_eur) for p in points] == [(date(2026, 8, 1), 40000.0), (date(2026, 8, 8), 38000.0)]


def test_unsorted_snapshots_still_come_back_oldest_first():
    points = price_points([_snap("a", 9, 38000.0), _snap("a", 2, 40000.0)])
    assert [p.on for p in points] == [date(2026, 8, 2), date(2026, 8, 9)]


def test_a_forint_listing_does_not_change_price_every_day_the_rate_moves():
    """price_eur drifts daily for a HUF car. Comparing that would invent a
    price change per day for every Hungarian listing - the same trap
    days_at_current_price documents."""
    snaps = [
        _snap("hu", 1, 28_400.0, original=10_390_000.0, currency="HUF"),
        _snap("hu", 2, 28_461.0, original=10_390_000.0, currency="HUF"),
        _snap("hu", 3, 28_390.0, original=10_390_000.0, currency="HUF"),
        _snap("hu", 4, 27_100.0, original=9_890_000.0, currency="HUF"),
    ]
    points = price_points(snaps)
    assert [p.price_original for p in points] == [10_390_000.0, 9_890_000.0]


def test_a_repricing_into_another_currency_counts_as_a_change():
    snaps = [_snap("a", 1, 40000.0, currency="EUR"), _snap("a", 2, 40000.0, original=40000.0, currency="HUF")]
    assert len(price_points(snaps)) == 2


def test_no_snapshots_no_points():
    assert price_points([]) == []


# --- the market ------------------------------------------------------------


def _model_of(ids, model="model_y"):
    return {i: model for i in ids}


def test_the_index_ignores_a_change_of_mix():
    """Six cars at 40k hold their price; on day two a batch of cheap cars
    arrives. The median asking price collapses - nobody changed a number."""
    ids = [f"c{i}" for i in range(6)]
    day_one = [_snap(i, 1, 40000.0) for i in ids]
    day_two = [_snap(i, 2, 40000.0) for i in ids] + [_snap(f"cheap{i}", 2, 20000.0) for i in range(6)]

    days = market_history(day_one + day_two, model_of=_model_of(ids + [f"cheap{i}" for i in range(6)]))

    assert days[0].median_eur == 40000.0
    assert days[1].median_eur < 40000.0, "the median follows the mix, as a median does"
    assert days[1].index == pytest.approx(100.0), "the index must not, because no car moved"


def test_the_index_follows_a_real_price_move():
    ids = [f"c{i}" for i in range(6)]
    day_one = [_snap(i, 1, 40000.0) for i in ids]
    day_two = [_snap(i, 2, 36000.0) for i in ids]  # every seller cut 10%

    days = market_history(day_one + day_two, model_of=_model_of(ids))

    assert days[1].index == pytest.approx(90.0)


def test_a_day_with_too_few_cars_is_not_reported():
    ids = [f"c{i}" for i in range(6)]
    snaps = [_snap(i, 1, 40000.0) for i in ids] + [_snap("c0", 2, 40000.0)]
    days = market_history(snaps, model_of=_model_of(ids))
    assert [d.on for d in days] == [date(2026, 8, 1)]


def test_too_little_overlap_holds_the_index_rather_than_guessing():
    """Two cars in common is one seller's decision, not the market's."""
    old = [f"o{i}" for i in range(6)]
    new = [f"n{i}" for i in range(6)]
    snaps = (
        [_snap(i, 1, 40000.0) for i in old]
        + [_snap(i, 2, 20000.0) for i in new]
        + [_snap(old[0], 2, 20000.0), _snap(old[1], 2, 20000.0)]
    )
    days = market_history(snaps, model_of=_model_of(old + new))
    assert days[1].index == pytest.approx(100.0)


def test_models_are_indexed_separately():
    y = [f"y{i}" for i in range(6)]
    three = [f"t{i}" for i in range(6)]
    snaps = (
        [_snap(i, 1, 40000.0) for i in y]
        + [_snap(i, 2, 36000.0) for i in y]
        + [_snap(i, 1, 30000.0) for i in three]
        + [_snap(i, 2, 30000.0) for i in three]
    )
    model_of = {**_model_of(y, "model_y"), **_model_of(three, "model_3")}
    days = market_history(snaps, model_of=model_of)
    by_model = {(d.model, d.on): d.index for d in days}
    assert by_model[("model_y", date(2026, 8, 2))] == pytest.approx(90.0)
    assert by_model[("model_3", date(2026, 8, 2))] == pytest.approx(100.0)


def test_a_day_scraped_twice_does_not_weight_those_cars_double():
    ids = [f"c{i}" for i in range(6)]
    snaps = [_snap(i, 1, 40000.0) for i in ids] + [_snap(i, 1, 40000.0) for i in ids]
    days = market_history(snaps, model_of=_model_of(ids))
    assert days[0].n == 6


def test_one_seller_cutting_moves_the_index_at_its_true_weight():
    """The property that makes the index worth having.

    Used-car prices change rarely - on a typical day none of a hundred
    sellers touches their number and a handful cut. A median of those
    ratios is exactly 1.0 unless over half the market repriced in one day,
    so a median-based index would be a flat line saying "nothing moved"
    while prices fell around it.
    """
    ids = [f"c{i}" for i in range(8)]
    day_one = [_snap(i, 1, 40000.0) for i in ids]
    day_two = [_snap(i, 2, 37500.0 if i == "c0" else 40000.0) for i in ids]

    days = market_history(day_one + day_two, model_of=_model_of(ids))

    # one car in eight cutting 6.25% -> 6.25% spread over eight cars
    assert days[1].index == pytest.approx(100 * (37500 / 40000) ** (1 / 8), rel=1e-6)
    assert 99.1 < days[1].index < 99.3


def test_an_impossible_overnight_move_is_dropped_not_averaged_in():
    """A car does not halve overnight; that is a mis-parsed price, and one
    of them would otherwise drag a whole day of the index with it."""
    ids = [f"c{i}" for i in range(8)]
    day_one = [_snap(i, 1, 40000.0) for i in ids]
    day_two = [_snap(i, 2, 400.0 if i == "c0" else 40000.0) for i in ids]

    days = market_history(day_one + day_two, model_of=_model_of(ids))

    assert days[1].index == pytest.approx(100.0)


# --- a price that is not a price -------------------------------------------


def test_a_snapshot_with_no_price_is_not_a_price_cut():
    """A source that cannot read the number off a card falls back to zero
    (AutoScout24's parser reads `priceRaw or 0`). Left in, that snapshot is
    a seller who dropped to nothing: a 100%-off badge at the top of the
    biggest-drop sort."""
    snaps = [_snap("a", 1, 40000.0), _snap("a", 2, 0.0), _snap("a", 3, 39000.0)]
    points = price_points(snaps)
    assert [(p.on, p.price_eur) for p in points] == [(date(2026, 8, 1), 40000.0), (date(2026, 8, 3), 39000.0)]


def test_a_car_priced_at_zero_is_left_out_of_the_market_median():
    """One unreadable card must not drag a whole day of the index down."""
    model_of = {f"c{i}": "model_y" for i in range(10)}
    snaps = [_snap(f"c{i}", 1, 40000.0) for i in range(9)] + [_snap("c9", 1, 0.0)]
    days = market_history(snaps, model_of=model_of)
    assert [(d.n, d.median_eur) for d in days] == [(9, 40000.0)]


def test_a_price_only_missing_in_the_original_currency_is_still_dropped():
    """price_eur is derived, so a zero original with a non-zero euro figure
    means the conversion invented a number the ad never carried."""
    assert price_points([_snap("a", 1, 40000.0, original=0.0, currency="HUF")]) == []
