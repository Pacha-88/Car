"""Per-listing derived status: how long a price has held, and whether a
listing is new. Both come straight out of the snapshot table (see
db/models.py's docstring on why history is snapshot-based) rather than
needing separate tracking.
"""

from __future__ import annotations

from datetime import date, datetime

from car_tracker.db.models import ListingSnapshot


# Marketplaces carry entries that aren't cars: referral links, accessory
# ads, deposit placeholders. A real one showed up as a 1 EUR "Tesla
# Empfehlungslink 1.000 Freikilometer" and, being a listing like any other,
# it entered the median price, the trend fit and the depreciation curve.
# No used Tesla sells for four figures, so a floor separates them cleanly
# without risking a real bargain (the cheapest genuine car in the same
# dataset was ~21.000 EUR).
MIN_PLAUSIBLE_PRICE_EUR = 3_000


def is_plausible_car(price_eur: float) -> bool:
    """False for entries too cheap to be an actual used Tesla."""
    return price_eur >= MIN_PLAUSIBLE_PRICE_EUR


def is_usable_price(snapshot: ListingSnapshot) -> bool:
    """Whether this snapshot recorded a price a car could actually have.

    Two ways it might not. A zero is not a price: nothing stores one
    deliberately, but a source that cannot find the number on a card falls
    back to it - AutoScout24's parser reads `priceRaw or 0` - and an
    unreadable price is a gap in the record, not a decision by the seller.
    And a euro is not a price either, it is a referral link; the export has
    always dropped those listings whole, but the readers below used to
    count them anyway, so an ad that is not a car sat in the market median
    and the quartiles it never appeared in the grid beside.

    Left in, either kind splits an unbroken run in two - reporting a price
    held for ten days as held for four - and reads to `price_points` as a
    seller who dropped to nothing.

    Shared by all three readers so the answers to "when did this price
    start", "what has this seller done" and "what is the market doing"
    cannot drift apart.
    """
    if not snapshot.price_original or snapshot.price_original <= 0:
        return False
    return snapshot.price_eur > 0 and is_plausible_car(snapshot.price_eur)


def days_at_current_price(snapshots: list[ListingSnapshot], *, as_of: datetime) -> int:
    """How many days the most recent price in `snapshots` has held.

    Walks back from the latest snapshot while the price is unchanged; the
    result is `as_of` minus the observed_at of the earliest snapshot in
    that unbroken run. `snapshots` need not be pre-sorted.

    "Unchanged" means the price the seller set - `price_original` in its
    own currency - NOT the EUR conversion. `price_eur` is derived with the
    day's ECB rate, so for a listing priced in forints it drifts a little
    every day the rate moves; comparing it made every Használtautó listing
    read "at this price for 0 days" forever, however long the seller had
    actually held the price. (Reproduced with a week of real-shaped HUF
    rates: an unchanged 14.500.000 Ft listing scored 0, the identical
    EUR-priced car 6.) The currency is part of the comparison so a genuine
    repricing in a different currency never counts as "the same price".
    """
    if not snapshots:
        raise ValueError("no snapshots to compute a price duration from")
    ordered = [s for s in sorted(snapshots, key=lambda s: s.observed_at) if is_usable_price(s)]
    if not ordered:
        return 0
    current = (ordered[-1].currency_original, ordered[-1].price_original)
    held_since = ordered[-1].observed_at
    for snapshot in reversed(ordered):
        if (snapshot.currency_original, snapshot.price_original) != current:
            break
        held_since = snapshot.observed_at
    return (as_of - held_since).days


def is_new_since_last_scrape(first_seen_at: datetime, *, latest_scrape_date: date) -> bool:
    """True if `first_seen_at` falls on the most recent day anything was scraped.

    Compared by calendar date rather than exact timestamp, since different
    sources scraped "the same day" won't share an identical datetime.
    """
    return first_seen_at.date() == latest_scrape_date
