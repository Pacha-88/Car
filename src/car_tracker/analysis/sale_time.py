"""How long a car sits on the market before it sells.

A retired listing is one its site stopped serving while we were looking -
for this dashboard's purpose, a sale. `last_seen_at - first_seen_at` is
its time on the market AS WITNESSED, and that qualifier is the whole
difficulty here.

**Left-censoring.** Every car already on sale the day this tracker started
carries `first_seen_at = tracking start` - a car that had sat for three
months and sold the next day would read "sold in 1 day". On day one that
is the entire population, so a naive median would open wildly optimistic
and drift toward the truth over weeks, which is worse than no number: it
looks precise exactly when it is most wrong. So only sales whose ARRIVAL
was also witnessed count - a listing first seen after its source's
tracking began. The cohort starts empty and every car in it has a true
span.

Tracking start is per SOURCE, not global: Használtautó.hu is scraped by
hand and joined later than AutoScout24 did, and measuring its listings
against the global start would sweep its whole day-one population into
the "witnessed" cohort.

**Which sales count.** Only listings that ever recorded a usable price -
the retirement of a 1 EUR referral link is not a sale. The caller passes
that set, since deciding it needs the snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

#: Fewer witnessed sales than this and a median is one seller's luck.
MIN_SOLD_SAMPLE = 5


@dataclass(frozen=True)
class SaleRow:
    """The slice of a listing this module needs."""

    listing_id: str
    source: str
    model: str
    variant: str | None
    first_seen: date
    last_seen: date
    is_active: bool


@dataclass(frozen=True)
class SaleTime:
    model: str
    #: None = every variant of the model together - the fallback a variant
    #: with too few witnessed sales of its own falls back to.
    variant: str | None
    median_days: float
    n: int


def sale_times(rows: list[SaleRow], *, min_sample: int = MIN_SOLD_SAMPLE) -> list[SaleTime]:
    """Median witnessed days-to-sale per (model, variant) and per model."""
    tracking_start: dict[str, date] = {}
    for row in rows:
        started = tracking_start.get(row.source)
        if started is None or row.first_seen < started:
            tracking_start[row.source] = row.first_seen

    spans: dict[tuple[str, str | None], list[int]] = {}
    for row in rows:
        if row.is_active:
            continue
        if row.first_seen <= tracking_start[row.source]:
            continue  # censored: it may have been on sale long before we looked
        # Seen once and gone the next scrape is a sub-day sale; zero would
        # read as "instantly", which overstates what one daily sample knows.
        days = max(1, (row.last_seen - row.first_seen).days)
        spans.setdefault((row.model, row.variant), []).append(days)
        spans.setdefault((row.model, None), []).append(days)

    out = [
        SaleTime(model=model, variant=variant, median_days=float(median(days)), n=len(days))
        for (model, variant), days in spans.items()
        if len(days) >= min_sample
    ]
    out.sort(key=lambda s: (s.model, s.variant or ""))
    return out
