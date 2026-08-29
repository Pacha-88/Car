"""What the stored snapshots say about prices over time.

Two different questions, and they need two different answers.

**One car.** `price_points` compresses a listing's snapshots to the moments
its price actually changed. A daily scrape writes a snapshot every day, so
a car listed for a month has thirty of them and one or two distinct prices;
keeping only the changes is what makes an "asked 14.9M, now 13.9M" badge
cheap enough to put in the export.

A change means the SELLER changed the number - `price_original` in its own
currency. `price_eur` drifts with the ECB rate every day a forint listing
sits there, so comparing that would invent a price change per day for every
Hungarian car, which is the same trap `days_at_current_price` documents.

**The market.** `market_history` is where mix has to be handled. The median
asking price of everything on sale is not the price of anything: it moves
when cheap cars arrive and when expensive ones sell, with no seller
changing a number. So each day also carries a chained index built only from
cars present on BOTH days - the median of their own price ratios. That is
the standard way a price index is made mix-proof, and it answers the actual
question ("did prices move?") rather than "did the shop window change?".

Snapshots of retired listings count here, unlike everywhere else in the
export: a car that sold is exactly the observation a market index must not
drop, or the index only ever tracks the cars nobody wanted.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from car_tracker.analysis.listing_status import has_price
from car_tracker.db.models import ListingSnapshot

# Below this many cars a daily median is noise, and below this many matched
# pairs a day's index step is one seller's decision rather than the market's.
MIN_DAY_SAMPLE = 5
MIN_MATCHED_PAIRS = 5

# ...and below this share of what the last few days saw, the scrape broke
# rather than the market shrinking. A run that hits a bot wall partway
# through stores a real but lopsided sample - every German car and no
# Hungarian ones, say - whose median is a fact about the outage, not about
# prices, and which the chart would otherwise draw as a one-day crash.
# Compared against recent days rather than the whole record so that adding
# a source, or a market that genuinely grows, does not retroactively
# invalidate everything before it.
MIN_SHARE_OF_RECENT = 0.5
RECENT_DAYS = 7


@dataclass(frozen=True)
class PricePoint:
    on: date
    price_eur: float
    price_original: float


def price_points(snapshots: list[ListingSnapshot]) -> list[PricePoint]:
    """One point per price the seller actually set, oldest first."""
    points: list[PricePoint] = []
    previous: tuple[str, float] | None = None
    for snapshot in sorted(snapshots, key=lambda s: s.observed_at):
        if not has_price(snapshot):
            continue
        asked = (snapshot.currency_original, snapshot.price_original)
        if asked == previous:
            continue
        previous = asked
        points.append(
            PricePoint(
                on=snapshot.observed_at.date(),
                price_eur=snapshot.price_eur,
                price_original=snapshot.price_original,
            )
        )
    return points


@dataclass(frozen=True)
class MarketDay:
    on: date
    model: str
    median_eur: float
    p25_eur: float
    p75_eur: float
    n: int
    #: 100 on the first day with enough data; moves only by the median price
    #: change of cars present on both that day and the one before.
    index: float


def _quartiles(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    if len(ordered) < 4:
        return ordered[0], ordered[-1]
    half = len(ordered) // 2
    return median(ordered[:half]), median(ordered[len(ordered) - half :])


def market_history(
    snapshots: list[ListingSnapshot],
    *,
    model_of: dict[str, str],
    min_day_sample: int = MIN_DAY_SAMPLE,
) -> list[MarketDay]:
    """A daily median and a mix-proof index per model, oldest first."""
    # (model, day) -> {listing_id: (price_eur, price_original)}
    by_day: dict[tuple[str, date], dict[str, tuple[float, float]]] = defaultdict(dict)
    for snapshot in snapshots:
        model = model_of.get(snapshot.listing_id)
        if model is None or not has_price(snapshot):
            continue
        # One snapshot per listing per day: a day scraped twice would
        # otherwise weight those cars double in the median.
        by_day[(model, snapshot.observed_at.date())][snapshot.listing_id] = (
            snapshot.price_eur,
            snapshot.price_original,
        )

    out: list[MarketDay] = []
    for model in sorted({model for model, _ in by_day}):
        days = sorted(day for m, day in by_day if m == model)
        index = 100.0
        previous_day: date | None = None
        recent_counts: list[int] = []
        for day in days:
            cars = by_day[(model, day)]
            if len(cars) < min_day_sample:
                continue
            partial = bool(recent_counts) and len(cars) < MIN_SHARE_OF_RECENT * median(recent_counts)
            # Recorded whether or not the day is reported, so the window
            # tracks what is actually being scraped. Gate on reported days
            # alone and a lasting drop in coverage - a country taken out of
            # the run, a source retired - measures itself against a level
            # that no longer exists and silently freezes the chart from
            # that day on. This way one bad day is dropped and a new normal
            # is absorbed within a week.
            recent_counts.append(len(cars))
            del recent_counts[:-RECENT_DAYS]
            if partial:
                # Skipping also keeps it out of the index: `previous_day`
                # stays put, so the next good day is chained against the
                # last good one rather than against a fragment.
                continue
            if previous_day is not None:
                index *= _step(by_day[(model, previous_day)], cars)
            previous_day = day
            prices = [eur for eur, _ in cars.values()]
            low, high = _quartiles(prices)
            out.append(
                MarketDay(
                    on=day,
                    model=model,
                    median_eur=median(prices),
                    p25_eur=low,
                    p75_eur=high,
                    n=len(prices),
                    index=index,
                )
            )
    return out


def _step(before: dict[str, tuple[float, float]], after: dict[str, tuple[float, float]]) -> float:
    """The average price ratio of the cars listed on both days.

    Only these cars can say anything about a price MOVE; a car that arrived
    or sold between the two days says something about the mix instead. The
    ratio uses the seller's own currency, which makes it unitless and
    immune to the rate drift that would otherwise show up as daily movement
    on every forint listing.

    A GEOMETRIC mean, not a median. Used-car prices change rarely: on a
    typical day none of a hundred sellers touches their number and a
    handful cut. The median of those ratios is exactly 1.0 unless more than
    half the market repriced on one day, which never happens - so a
    median-based index is a flat line that says "nothing moved" while
    prices fall all around it. The geometric mean of ratios is what a real
    price index uses for the same reason (it is the Jevons index), and it
    carries a single seller's cut through at its true weight: one car in
    eight cutting 6% moves the index 0.8%.

    Ratios outside [0.5, 2] are dropped: a used car does not halve or
    double overnight, so that is a data error - a mis-parsed price, a
    currency mix-up - and one of them would otherwise drag a whole day.
    """
    ratios = [
        after[listing_id][1] / before[listing_id][1]
        for listing_id in after.keys() & before.keys()
        if before[listing_id][1] > 0
    ]
    usable = [r for r in ratios if 0.5 <= r <= 2.0]
    if len(usable) < MIN_MATCHED_PAIRS:
        return 1.0  # not enough overlap to claim a move; hold the index flat
    return math.exp(sum(math.log(r) for r in usable) / len(usable))
