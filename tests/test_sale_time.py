"""analysis/sale_time.py - how long a car sits before it sells."""

from datetime import date

from car_tracker.analysis.sale_time import SaleRow, sale_times


def _row(i, *, source="autoscout24", model="model_y", variant="rwd", first, last, active=False):
    return SaleRow(
        listing_id=f"{source}:{i}",
        source=source,
        model=model,
        variant=variant,
        first_seen=first,
        last_seen=last,
        is_active=active,
    )


START = date(2026, 8, 1)


def _population(source="autoscout24"):
    """A day-one population, so the tracking start is anchored."""
    return [_row(f"seed{i}", source=source, first=START, last=date(2026, 8, 29), active=True) for i in range(3)]


def test_a_sale_first_seen_on_day_one_is_censored_not_fast():
    """A car already on sale when tracking began may have sat for months -
    counting it would open the median wildly optimistic and let it drift
    toward the truth over weeks, precise-looking exactly when wrongest."""
    rows = _population() + [
        _row(i, first=START, last=date(2026, 8, 2)) for i in range(6)  # "sold in a day" - we cannot know
    ]
    assert sale_times(rows) == []


def test_witnessed_arrivals_make_the_median():
    rows = _population() + [
        _row(i, first=date(2026, 8, 5), last=date(2026, 8, 5 + days))
        for i, days in enumerate((3, 7, 10, 14, 21))
    ]
    stats = sale_times(rows)
    assert {(s.model, s.variant, s.median_days, s.n) for s in stats} == {
        ("model_y", "rwd", 10.0, 5),
        ("model_y", None, 10.0, 5),
    }


def test_four_sales_are_not_a_median():
    rows = _population() + [
        _row(i, first=date(2026, 8, 5), last=date(2026, 8, 10)) for i in range(4)
    ]
    assert sale_times(rows) == []


def test_active_listings_are_not_sales():
    rows = _population() + [
        _row(i, first=date(2026, 8, 5), last=date(2026, 8, 29), active=True) for i in range(9)
    ]
    assert sale_times(rows) == []


def test_tracking_starts_are_per_source():
    """Használtautó joined weeks after AutoScout24; its day-one population
    must be censored against ITS start, not the global one."""
    rows = _population(source="autoscout24") + [
        # hasznaltauto's very first sighting is Aug 20 - all five of these
        # are its day-one cohort, however late that is globally.
        _row(i, source="hasznaltauto", first=date(2026, 8, 20), last=date(2026, 8, 22)) for i in range(5)
    ]
    assert sale_times(rows) == []


def test_a_sub_day_sale_counts_one_day_not_zero():
    rows = _population() + [
        _row(i, first=date(2026, 8, 5), last=date(2026, 8, 5)) for i in range(5)
    ]
    stats = sale_times(rows)
    assert all(s.median_days == 1.0 for s in stats)


def test_a_variant_with_too_few_sales_still_feeds_the_model_rollup():
    rows = _population() + [
        _row(f"a{i}", variant="rwd", first=date(2026, 8, 5), last=date(2026, 8, 8)) for i in range(3)
    ] + [
        _row(f"b{i}", variant="performance", first=date(2026, 8, 5), last=date(2026, 8, 12)) for i in range(3)
    ]
    stats = sale_times(rows)
    # Neither variant reaches five on its own; together the model does.
    assert [(s.variant, s.n) for s in stats] == [(None, 6)]
