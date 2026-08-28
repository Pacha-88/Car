"""Command-line entry points for running scrapes and inspecting sources."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from car_tracker.db.models import Listing, ListingSnapshot
from car_tracker.db.session import init_db, session_scope
from car_tracker.normalize.chassis import detect_chassis
from car_tracker.normalize.currency import to_eur
from car_tracker.normalize.variant import normalize_variant
from car_tracker.sources.autoscout24 import AutoScout24Source
from car_tracker.sources.base import RawListing
from car_tracker.sources.tesla import TeslaSource

SOURCES = {"tesla": TeslaSource, "autoscout24": AutoScout24Source}
COUNTRIES = ["DE", "AT", "HU"]
MODELS = ["model_y", "model_3"]


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db()
    print("db initialized")


def cmd_tesla_raw_sample(args: argparse.Namespace) -> None:
    """Fetch one raw page, unparsed — the tool for checking parse_item()
    against a real response once this environment can reach tesla.com."""
    with TeslaSource() as source:
        page = source.fetch_raw_page(model=args.model, country=args.country)
    print(json.dumps(page, indent=2))


def cmd_scrape(args: argparse.Namespace) -> None:
    if args.source not in SOURCES:
        raise SystemExit(f"unknown source {args.source!r}, expected one of {sorted(SOURCES)}")

    source_cls = SOURCES[args.source]
    with source_cls() as source:
        raw_listings = source.fetch_listings(model=args.model, country=args.country, max_pages=args.max_pages)

    # TODO(F1): replace with fx/ecb.py rates loaded from the fx_rates table
    # once that's wired up; a manual override is enough to prove the pipeline.
    rates_to_eur = {"EUR": 1.0}
    if args.huf_rate is not None:
        rates_to_eur["HUF"] = args.huf_rate

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        for raw in raw_listings:
            _upsert(session, raw, rates_to_eur=rates_to_eur, observed_at=now)
    print(f"stored {len(raw_listings)} listings from {args.source}/{args.model}/{args.country}")


def _upsert(session, raw: RawListing, *, rates_to_eur: dict[str, float], observed_at: datetime) -> None:
    listing_id = f"{raw.source}:{raw.source_listing_id}"
    listing = session.get(Listing, listing_id)
    chassis_gen = detect_chassis(
        raw.model, first_registration=raw.first_registration, model_year=raw.model_year, title=raw.title_raw
    )
    variant = normalize_variant(raw.variant)

    if listing is None:
        listing = Listing(
            id=listing_id,
            source=raw.source,
            source_listing_id=raw.source_listing_id,
            model=raw.model,
            chassis_gen=chassis_gen,
            variant=variant,
            country=raw.country,
            model_year=raw.model_year,
            first_registration=raw.first_registration,
            url=raw.url,
            title_raw=raw.title_raw,
            photo_urls=raw.photo_urls,
            seller_type=raw.seller_type,
            location=raw.location,
            power_kw=raw.power_kw,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            is_active=True,
        )
        session.add(listing)
    else:
        listing.last_seen_at = observed_at
        listing.is_active = True
        listing.chassis_gen = chassis_gen or listing.chassis_gen
        listing.variant = variant or listing.variant
        listing.power_kw = raw.power_kw or listing.power_kw

    session.add(
        ListingSnapshot(
            listing_id=listing_id,
            observed_at=observed_at,
            price_original=raw.price_original,
            currency_original=raw.currency_original,
            price_eur=to_eur(raw.price_original, raw.currency_original, rates_to_eur),
            mileage_km=raw.mileage_km,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="car-tracker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init-db", help="create tables in the configured database")
    p_init.set_defaults(func=cmd_init_db)

    p_sample = subparsers.add_parser(
        "tesla-raw-sample", help="fetch one raw Tesla inventory page for inspection (no DB writes)"
    )
    p_sample.add_argument("--model", choices=MODELS, required=True)
    p_sample.add_argument("--country", choices=COUNTRIES, required=True)
    p_sample.set_defaults(func=cmd_tesla_raw_sample)

    p_scrape = subparsers.add_parser("scrape", help="scrape one source/model/country and store snapshots")
    p_scrape.add_argument("--source", required=True, choices=sorted(SOURCES))
    p_scrape.add_argument("--model", choices=MODELS, required=True)
    # Not choice-constrained here: country coverage differs per source (e.g.
    # autoscout24 also does NL/BE/IT/ES/FR/LU, tesla doesn't); each source
    # validates its own country and raises a clear error.
    p_scrape.add_argument("--country", required=True)
    p_scrape.add_argument("--huf-rate", type=float, default=None, help="manual HUF->EUR override until fx/ecb.py is wired up")
    p_scrape.add_argument("--max-pages", type=int, default=None, help="cap result pages fetched (default: no cap)")
    p_scrape.set_defaults(func=cmd_scrape)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
