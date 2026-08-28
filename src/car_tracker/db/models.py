"""SQLAlchemy models — SQLite locally, Postgres/Supabase in production.

Snapshot-based history: every scrape run inserts a ListingSnapshot row for
each listing it sees. "Current" state is always the latest snapshot for a
listing. Price-change history, "days at this price", and "new since last
scrape" are all derived from this table rather than tracked separately.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Listing(Base):
    """One physical listing at one source. Identity is stable across scrapes;
    price/mileage move to ListingSnapshot instead of being overwritten here.
    """

    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # f"{source}:{source_listing_id}"
    source: Mapped[str] = mapped_column(String, index=True)  # "tesla" | "autoscout24" | "kleinanzeigen" | "hasznaltauto" | ...
    source_listing_id: Mapped[str] = mapped_column(String)

    model: Mapped[str] = mapped_column(String, index=True)  # "model_y" | "model_3"
    chassis_gen: Mapped[str | None] = mapped_column(String, nullable=True)  # "legacy" | "highland" | "juniper" | None
    variant: Mapped[str | None] = mapped_column(String, nullable=True)  # "rwd" | "long_range_awd" | "performance" | ...

    country: Mapped[str] = mapped_column(String, index=True)  # "DE" | "AT" | "HU" | other ISO-3166-1 alpha-2 for "Rest of EU"
    model_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_registration: Mapped[date | None] = mapped_column(Date, nullable=True)

    url: Mapped[str] = mapped_column(String)
    title_raw: Mapped[str | None] = mapped_column(String, nullable=True)  # kept for re-parsing when heuristics improve
    photo_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    seller_type: Mapped[str | None] = mapped_column(String, nullable=True)  # "dealer" | "private" | "tesla"
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    power_kw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # False once a scrape no longer finds it

    snapshots: Mapped[list["ListingSnapshot"]] = relationship(
        back_populates="listing", order_by="ListingSnapshot.observed_at", cascade="all, delete-orphan"
    )


class ListingSnapshot(Base):
    """One observation of a listing's price/mileage at scrape time."""

    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    price_original: Mapped[float] = mapped_column(Float)
    currency_original: Mapped[str] = mapped_column(String)
    price_eur: Mapped[float] = mapped_column(Float)
    mileage_km: Mapped[int | None] = mapped_column(Integer, nullable=True)

    listing: Mapped[Listing] = relationship(back_populates="snapshots")


class FxRate(Base):
    """Daily reference rate: 1 unit of `currency` = rate_to_eur EUR."""

    __tablename__ = "fx_rates"

    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(String, primary_key=True)
    rate_to_eur: Mapped[float] = mapped_column(Float)
