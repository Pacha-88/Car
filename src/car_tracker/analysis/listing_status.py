"""Per-listing derived status: how long a price has held, and whether a
listing is new. Both come straight out of the snapshot table (see
db/models.py's docstring on why history is snapshot-based) rather than
needing separate tracking.
"""

from __future__ import annotations

from datetime import date, datetime

from car_tracker.db.models import ListingSnapshot


def days_at_current_price(snapshots: list[ListingSnapshot], *, as_of: datetime) -> int:
    """How many days the most recent price in `snapshots` has held.

    Walks back from the latest snapshot while the price is unchanged; the
    result is `as_of` minus the observed_at of the earliest snapshot in
    that unbroken run. `snapshots` need not be pre-sorted.
    """
    if not snapshots:
        raise ValueError("no snapshots to compute a price duration from")
    ordered = sorted(snapshots, key=lambda s: s.observed_at)
    current_price = ordered[-1].price_eur
    held_since = ordered[-1].observed_at
    for snapshot in reversed(ordered):
        if snapshot.price_eur != current_price:
            break
        held_since = snapshot.observed_at
    return (as_of - held_since).days


def is_new_since_last_scrape(first_seen_at: datetime, *, latest_scrape_date: date) -> bool:
    """True if `first_seen_at` falls on the most recent day anything was scraped.

    Compared by calendar date rather than exact timestamp, since different
    sources scraped "the same day" won't share an identical datetime.
    """
    return first_seen_at.date() == latest_scrape_date
