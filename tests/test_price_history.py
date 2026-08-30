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


# --- a run that broke halfway ----------------------------------------------


def _day(model_of, day, count, price):
    for i in range(count):
        model_of[f"c{i}"] = "model_y"
    return [_snap(f"c{i}", day, price) for i in range(count)]


def test_a_scrape_that_broke_partway_is_not_a_one_day_crash():
    """A run that hits a bot wall partway through observes only a subset -
    at their true, unchanged prices. The cars the broken run missed are
    carried at their last known price, so the day's median is a fact about
    the market, not the outage, and the index steps only on what was
    actually seen."""
    model_of: dict[str, str] = {}
    snaps: list = []
    for day in range(1, 7):
        snaps += _day(model_of, day, 300, 40000.0)
    snaps += _day(model_of, 7, 20, 40000.0)  # the wall: 20 cars seen, 280 missed
    for day in (8, 9):
        snaps += _day(model_of, day, 300, 40000.0)

    days = market_history(snaps, model_of=model_of)
    assert [d.on.day for d in days] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    wall = next(d for d in days if d.on.day == 7)
    assert wall.n == 300, "the missed cars are carried, not gone"
    assert wall.median_eur == 40000.0
    assert wall.matched_pairs == 20, "the step uses only what the run saw"
    assert all(d.index == pytest.approx(100.0) for d in days)


def test_sources_on_different_cadences_do_not_sawtooth_the_median():
    """The CI scrapes AutoScout24 daily; Használtautó moves only on manual
    runs. On a plain CI day the Hungarian cars used to vanish from the
    sample, swinging the median ~4% with nobody repricing anything - and
    swinging it back on the next manual run."""
    model_of: dict[str, str] = {}
    snaps: list = []
    for day in range(1, 7):
        snaps += _day(model_of, day, 20, 34000.0)  # scraped daily
    for label, day in (("a", 1), ("b", 6)):  # scraped only on manual-run days
        for i in range(20):
            model_of[f"hu{i}"] = "model_y"
            snaps.append(_snap(f"hu{i}", day, 38000.0))
        del label

    days = market_history(snaps, model_of=model_of)
    assert [d.n for d in days] == [40] * 6, "believed on sale, not observed today"
    assert all(d.median_eur == 36000.0 for d in days), "no sawtooth"
    assert all(d.index == pytest.approx(100.0) for d in days)


def test_a_real_move_survives_a_day_with_no_overlap():
    """The index base only advances when a step was measured. Advancing it
    regardless lost real moves: a fleet repriced 10% across a day of
    one-day visitors came back with the index still at 100."""
    model_of = {f"c{i}": "model_y" for i in range(10)} | {f"x{i}": "model_y" for i in range(6)}
    snaps = (
        [_snap(f"c{i}", 1, 40000.0) for i in range(10)]
        + [_snap(f"x{i}", 2, 40000.0) for i in range(6)]
        + [_snap(f"c{i}", 3, 36000.0) for i in range(10)]
    )
    days = market_history(snaps, model_of=model_of)
    assert [round(d.index, 2) for d in days] == [100.0, 100.0, 90.0]
    assert [d.matched_pairs for d in days] == [0, 0, 10]


def test_a_lasting_drop_in_coverage_becomes_the_new_normal():
    """A country taken out of the run: its cars' alive ranges end, the
    carried set shrinks to what is really still tracked, and every later
    day reports at the new level."""
    model_of: dict[str, str] = {}
    snaps: list = []
    for day in range(1, 7):
        snaps += _day(model_of, day, 300, 40000.0)
    for day in range(7, 17):
        snaps += _day(model_of, day, 30, 40000.0)

    days = market_history(snaps, model_of=model_of)
    assert [d.on.day for d in days] == list(range(1, 17))
    assert days[-1].n == 30, "the departed cars stop being carried"
    assert days[0].n == 300


def test_an_index_held_for_want_of_overlap_says_so():
    """A step of 1.0 means two different things - "these cars held their
    prices" and "there were no cars to look at". Reported as a flat index
    with nothing to distinguish them, a market climbing 1000 a day showed
    "+0,0% counting only cars on sale the whole time"."""
    model_of: dict[str, str] = {}
    snaps: list = []
    for day in range(1, 7):
        for i in range(6):  # a fleet that turns over completely every day
            listing_id = f"d{day}_{i}"
            model_of[listing_id] = "model_3"
            snaps.append(_snap(listing_id, day, 30000.0 + day * 1000))

    days = market_history(snaps, model_of=model_of)
    assert [d.median_eur for d in days] == [31000.0, 32000.0, 33000.0, 34000.0, 35000.0, 36000.0]
    assert all(d.index == 100.0 for d in days), "held flat, correctly"
    assert all(d.matched_pairs == 0 for d in days), "and the reason is carried out with it"


def test_a_measured_step_reports_how_many_cars_backed_it():
    model_of = {f"c{i}": "model_y" for i in range(10)}
    snaps = [_snap(f"c{i}", 1, 40000.0) for i in range(10)] + [_snap(f"c{i}", 2, 38000.0) for i in range(10)]
    days = market_history(snaps, model_of=model_of)
    assert [d.matched_pairs for d in days] == [0, 10]


def test_a_referral_link_is_not_a_car_in_the_market_median():
    """The export has always dropped these listings whole - a 1 EUR "Tesla
    Empfehlungslink" is not a used car - but the market readers counted
    them anyway, so an entry that never appeared in the grid sat in the
    median and the quartiles beside it."""
    model_of = {f"c{i}": "model_y" for i in range(9)}
    model_of["link"] = "model_y"
    snaps = [_snap(f"c{i}", 1, 40000.0) for i in range(9)] + [_snap("link", 1, 1.0)]
    days = market_history(snaps, model_of=model_of)
    assert [(d.n, d.median_eur) for d in days] == [(9, 40000.0)]


def test_a_car_that_reads_as_a_euro_for_one_scrape_has_not_been_given_away():
    snaps = [_snap("a", 1, 40000.0), _snap("a", 2, 1.0), _snap("a", 3, 39000.0)]
    assert [p.price_eur for p in price_points(snaps)] == [40000.0, 39000.0]


def test_active_cars_are_carried_past_their_last_scrape():
    """The trailing edge of the cadence fix: after the LAST manual run
    nothing newer exists for the Hungarian cars, so bounding their life by
    their last snapshot dropped the whole cohort the day after that run -
    the exact days a reader looks at. The caller says who is still active;
    a retired car still stops at its own last sighting."""
    model_of: dict[str, str] = {}
    snaps: list = []
    for day in range(1, 7):
        snaps += _day(model_of, day, 20, 34000.0)
    for i in range(20):
        model_of[f"hu{i}"] = "model_y"
        snaps.append(_snap(f"hu{i}", 1, 38000.0))  # one manual run, then silence

    still_active = {lid: date(2026, 8, 6) for lid in model_of}
    days = market_history(snaps, model_of=model_of, alive_until=still_active)
    assert [d.n for d in days] == [40] * 6, "still-active cars stay carried"

    retired_after_day_one = dict(still_active)
    for i in range(20):
        retired_after_day_one[f"hu{i}"] = date(2026, 8, 1)
    days = market_history(snaps, model_of=model_of, alive_until=retired_after_day_one)
    assert [d.n for d in days] == [40, 20, 20, 20, 20, 20], "a real exit still shows"
