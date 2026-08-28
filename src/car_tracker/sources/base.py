"""Common interface every source scraper implements.

A scraper's job stops at producing RawListing objects. Currency conversion,
chassis detection, and persistence all happen in one shared place afterwards
(see normalize/ and db/), so adding a new source never means re-implementing
that logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawListing:
    """What a scraper hands back for one listing, before normalization.

    Fields a source can't provide are left None/empty — normalization
    (chassis detection in particular) degrades gracefully when data is
    missing rather than requiring every field.
    """

    source: str
    source_listing_id: str
    model: str  # "model_3" | "model_y"
    country: str  # ISO-3166-1 alpha-2
    url: str
    price_original: float
    currency_original: str
    mileage_km: int | None = None
    model_year: int | None = None
    first_registration: date | None = None
    variant: str | None = None
    title_raw: str | None = None
    photo_urls: list[str] = field(default_factory=list)
    seller_type: str | None = None
    location: str | None = None


class Source(ABC):
    """One scrapeable source (a site, or a site+market pairing)."""

    name: str

    @abstractmethod
    def fetch_listings(self, *, model: str, country: str) -> list[RawListing]:
        """Return every currently-listed car for `model` in `country`."""
