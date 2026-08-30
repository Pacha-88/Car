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

from car_tracker.analysis.listing_status import is_usable_price
from car_tracker.db.models import ListingSnapshot

# Below this many cars a daily median is noise, and below this many matched
# pairs a day's index step is one seller's decision rather than the market's.
MIN_DAY_SAMPLE = 5
MIN_MATCHED_PAIRS = 5


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
        if not is_usable_price(snapshot):
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
    #: 100 on the first day with enough data; moves only by the price
    #: changes of cars present on both that day and the one before.
    index: float
    #: How many cars backed the step INTO this day. Zero on the first day,
    #: and on any day whose overlap with the one before was too thin to
    #: measure - there the index is HELD, not measured, and a reader told
    #: "0,0%" would hear "these cars did not move" when the truth is that
    #: nobody knows. Carried so the dashboard can tell the two apart.
    matched_pairs: int


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
    alive_until: dict[str, date] | None = None,
    min_day_sample: int = MIN_DAY_SAMPLE,
) -> list[MarketDay]:
    """A daily median and a mix-proof index per model, oldest first.

    The median is taken over every car BELIEVED ON SALE that day, not just
    the cars whose source happened to be scraped that day: between two
    observations a listing keeps its last asked price. Without that, the
    sources' different cadences write themselves into the series - the CI
    scrapes AutoScout24 daily while Használtautó moves only when someone
    runs scrape-local from home, so on a plain CI day the Hungarian cars
    vanished from the sample and the median swung ~4% with nobody
    repricing anything, then swung back on the next manual run. A car is
    believed on sale from its first usable snapshot until `alive_until`
    says otherwise - the caller knows which listings are still active,
    which snapshots alone cannot say: without it, every Hungarian car
    dropped out again the day AFTER the last manual run, the exact days a
    reader looks at, because nothing later than that run exists yet. A car
    the site retired stops being carried at its own last sighting. Absent
    the mapping, a listing's last snapshot bounds it (the conservative
    reading). A partial scrape likewise no longer distorts the median,
    because the cars the broken run missed are carried at their last known
    price.

    The index is stricter: carried prices claim "unchanged", which is not
    knowledge, so its steps use only prices actually OBSERVED on both of
    the two days being compared - and the comparison base only advances
    when a step was actually measured (enough matched pairs). Advancing it
    regardless lost real moves: a fleet repriced 10% across a day it did
    not overlap with came back with the index still at 100, because the
    base had moved past the day the old prices were last seen.
    """
    # (model, day) -> {listing_id: (price_eur, price_original)}, observed.
    by_day: dict[tuple[str, date], dict[str, tuple[float, float]]] = defaultdict(dict)
    # listing -> its usable price points, in day order, for carry-forward.
    points_of: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    for snapshot in snapshots:
        model = model_of.get(snapshot.listing_id)
        if model is None or not is_usable_price(snapshot):
            continue
        # One snapshot per listing per day: a day scraped twice would
        # otherwise weight those cars double in the median.
        by_day[(model, snapshot.observed_at.date())][snapshot.listing_id] = (
            snapshot.price_eur,
            snapshot.price_original,
        )
    for (model, day), cars in by_day.items():
        for listing_id, prices in cars.items():
            points_of[listing_id].append((day, *prices))
    for point_list in points_of.values():
        point_list.sort()

    out: list[MarketDay] = []
    for model in sorted({model for model, _ in by_day}):
        days = sorted(day for m, day in by_day if m == model)
        model_points = {
            listing_id: pts for listing_id, pts in points_of.items() if model_of.get(listing_id) == model
        }
        index = 100.0
        # The observed prices of the last day a step could be MEASURED
        # against. Held deliberately across low-overlap days.
        base: dict[str, tuple[float, float]] | None = None
        for day in days:
            observed = by_day[(model, day)]
            pairs = 0
            if base is None:
                base = observed
            else:
                step, pairs = _step(base, observed)
                if pairs:
                    index *= step
                    base = observed
            # Everyone believed on sale today, at their last known price.
            carried: list[float] = []
            for listing_id, pts in model_points.items():
                last_day = alive_until.get(listing_id, pts[-1][0]) if alive_until else pts[-1][0]
                if pts[0][0] <= day <= last_day:
                    latest = max(pt for pt in pts if pt[0] <= day)
                    carried.append(latest[1])
            if len(carried) < min_day_sample:
                continue
            low, high = _quartiles(carried)
            out.append(
                MarketDay(
                    on=day,
                    model=model,
                    median_eur=median(carried),
                    p25_eur=low,
                    p75_eur=high,
                    n=len(carried),
                    index=index,
                    matched_pairs=pairs,
                )
            )
    return out


def _step(before: dict[str, tuple[float, float]], after: dict[str, tuple[float, float]]) -> tuple[float, int]:
    """The average price ratio of the cars listed on both days, and how many.

    The count comes back with the ratio because a step of exactly 1.0 means
    two different things - "these cars held their prices" and "there were
    no cars to look at" - and only the caller can say which the reader
    needs to hear.

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
        return 1.0, 0  # not enough overlap to claim a move; hold the index flat
    return math.exp(sum(math.log(r) for r in usable) / len(usable)), len(usable)
