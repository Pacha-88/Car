"""Command-line entry points for running scrapes and inspecting sources."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select, update

from car_tracker.analysis.listing_status import days_at_current_price, is_new_since_last_scrape
from car_tracker.db.models import Listing, ListingSnapshot
from car_tracker.db.session import init_db, session_scope
from car_tracker.fx.ecb import fetch_latest_rates
from car_tracker.normalize.chassis import detect_chassis
from car_tracker.normalize.currency import EUR, market_currency, to_eur
from car_tracker.normalize.variant import normalize_variant
from car_tracker.sources.autoscout24 import COUNTRY_CODES as AUTOSCOUT24_COUNTRIES
from car_tracker.sources.autoscout24 import AutoScout24Source
from car_tracker.sources.base import RawListing
from car_tracker.sources.hasznaltauto import HasznaltautoSource
from car_tracker.sources.kleinanzeigen import KleinanzeigenSource
from car_tracker.sources.tesla import TeslaSource
from car_tracker.timeutil import utc_now

SOURCES = {
    "tesla": TeslaSource,
    "autoscout24": AutoScout24Source,
    "kleinanzeigen": KleinanzeigenSource,
    "hasznaltauto": HasznaltautoSource,
}
COUNTRIES = ["DE", "AT", "HU"]
MODELS = ["model_y", "model_3"]

# Every source/model/country combo `scrape-all` covers in one run — the
# daily-cron entry point. AutoScout24 gets its full country list (not just
# DE/AT) since those extra eurozone markets are exactly what feeds the
# dashboard's "Rest of EU" bucket; HU is excluded there because it returns
# zero results (see sources/autoscout24.py's docstring).
SCRAPE_TARGETS: dict[str, dict[str, list[str]]] = {
    "tesla": {"models": MODELS, "countries": ["DE", "AT", "HU"]},
    "autoscout24": {"models": MODELS, "countries": sorted(AUTOSCOUT24_COUNTRIES)},
    "kleinanzeigen": {"models": MODELS, "countries": ["DE"]},
    "hasznaltauto": {"models": MODELS, "countries": ["HU"]},
}

# Sources that refuse datacenter traffic outright, so the GitHub Actions run
# can never reach them however it presents itself. Verified 2026-08-28 from
# two independent datacenter networks (this project's dev sandbox and the
# Actions runner): Használtautó.hu returns Cloudflare's "Sorry, you have
# been blocked" — the hard WAF block, not the solvable "Just a moment..."
# JS challenge — and Tesla.com returns Akamai "Access Denied". Neither is a
# fingerprint problem, so neither a fuller header set (see sources/http.py,
# which did fix Kleinanzeigen) nor a real headless browser gets past them;
# only the origin of the request matters.
#
# `scrape-local` therefore exists to run these two from an ordinary home
# connection, which serves them normally, writing to the same database the
# scheduled run uses. See docs/DEPLOYMENT.md.
DATACENTER_BLOCKED_SOURCES = ("tesla", "hasznaltauto")


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db()
    print("db initialized")


def cmd_tesla_raw_sample(args: argparse.Namespace) -> None:
    """Fetch one raw page, unparsed — the tool for checking parse_item()
    against a real response once this environment can reach tesla.com."""
    with TeslaSource() as source:
        page = source.fetch_raw_page(model=args.model, country=args.country)
    print(json.dumps(page, indent=2))


def _rates_for_country(country: str, *, huf_rate_override: float | None) -> dict[str, float]:
    """EUR passthrough, plus whatever non-EUR rate this country needs.

    An explicit --huf-rate always wins. Otherwise, only reaches out to the
    ECB when the country actually needs a non-EUR rate — so e.g. a DE-only
    manual `scrape` still works without network access to ecb.europa.eu.
    """
    rates_to_eur = {EUR: 1.0}
    if huf_rate_override is not None:
        rates_to_eur["HUF"] = huf_rate_override
    elif market_currency(country) != EUR:
        _, ecb_rates = fetch_latest_rates()
        rates_to_eur.update(ecb_rates)
    return rates_to_eur


def cmd_scrape(args: argparse.Namespace) -> None:
    if args.source not in SOURCES:
        raise SystemExit(f"unknown source {args.source!r}, expected one of {sorted(SOURCES)}")

    source_cls = SOURCES[args.source]
    with source_cls() as source:
        raw_listings = source.fetch_listings(model=args.model, country=args.country, max_pages=args.max_pages)

    rates_to_eur = _rates_for_country(args.country, huf_rate_override=args.huf_rate)

    now = utc_now()
    with session_scope() as session:
        for raw in raw_listings:
            _upsert(session, raw, rates_to_eur=rates_to_eur, observed_at=now)
    print(f"stored {len(raw_listings)} listings from {args.source}/{args.model}/{args.country}")


def _run_scrape(targets: dict[str, dict[str, list[str]]], *, max_pages: int | None, label: str) -> None:
    """Scrape every combo in `targets` once, then retire what's gone.

    Best-effort per combo — one source failing (a site's markup changed, a
    temporary block) doesn't stop the others from running or being stored —
    but every failure is still surfaced (non-zero exit at the end) so it
    doesn't decay silently into "the dashboard just quietly has less data."

    Shared by `scrape-all` and `scrape-local`, which differ only in which
    sources they cover and therefore which ones they may retire.
    """
    rate_date, ecb_rates = fetch_latest_rates()
    rates_to_eur = {EUR: 1.0, **ecb_rates}
    print(f"fx rates as of {rate_date} (HUF={rates_to_eur.get('HUF')})")

    now = utc_now()
    total_stored = 0
    failures: list[str] = []
    failed_sources: set[str] = set()

    for source_name, target in targets.items():
        source_cls = SOURCES[source_name]
        for model in target["models"]:
            for country in target["countries"]:
                combo = f"{source_name}/{model}/{country}"
                try:
                    with source_cls() as source:
                        raw_listings = source.fetch_listings(model=model, country=country, max_pages=max_pages)
                    with session_scope() as session:
                        for raw in raw_listings:
                            _upsert(session, raw, rates_to_eur=rates_to_eur, observed_at=now)
                    print(f"ok    {combo}: {len(raw_listings)} listings")
                    total_stored += len(raw_listings)
                except Exception as exc:  # noqa: BLE001 - one combo's failure must not abort the rest
                    print(f"FAILED {combo}: {exc}")
                    failures.append(combo)
                    failed_sources.add(source_name)

    retired = _retire_unseen(now, sources=targets, skip_sources=failed_sources)
    for source_name, count in sorted(retired.items()):
        print(f"retired {source_name}: {count} listing(s) no longer on the site")
    for source_name in sorted(failed_sources):
        print(f"kept    {source_name}: not retiring anything, this source had failing combo(s) this run")

    print(f"{label} done: {total_stored} listings stored across {len(targets)} sources, {len(failures)} combo(s) failed")
    if failures:
        raise SystemExit(f"failed combos: {', '.join(failures)}")


def cmd_scrape_all(args: argparse.Namespace) -> None:
    """Every source the scheduled run can actually reach (see .github/workflows/).

    Skips DATACENTER_BLOCKED_SOURCES by default: including them would mean
    a permanently red daily run and a log full of expected 403s, which is
    how a real failure gets missed. Those are `scrape-local`'s job.
    """
    targets = {
        name: target
        for name, target in SCRAPE_TARGETS.items()
        if args.include_blocked or name not in DATACENTER_BLOCKED_SOURCES
    }
    if not args.include_blocked:
        print(f"skipping {', '.join(DATACENTER_BLOCKED_SOURCES)} - datacenter-blocked, run `car-tracker scrape-local` from home")
    _run_scrape(targets, max_pages=args.max_pages, label="scrape-all")


def cmd_scrape_local(args: argparse.Namespace) -> None:
    """The sources only a home connection can reach (DATACENTER_BLOCKED_SOURCES).

    Run this from an ordinary residential connection, pointed at the same
    DATABASE_URL the scheduled run uses. It touches only its own sources,
    so it never disturbs what the scheduled run collected — and vice versa.
    """
    targets = {name: SCRAPE_TARGETS[name] for name in DATACENTER_BLOCKED_SOURCES}
    _run_scrape(targets, max_pages=args.max_pages, label="scrape-local")


def _retire_unseen(
    run_started_at: datetime, *, sources: dict[str, dict[str, list[str]]], skip_sources: set[str]
) -> dict[str, int]:
    """Mark listings a completed scrape no longer found as inactive.

    Without this, sold and withdrawn cars accumulate forever: `_upsert`
    only ever sets `is_active` True. Within weeks the dashboard would be
    mostly dead listings, dragging the medians and the depreciation curve
    with them.

    A listing is retired when its `last_seen_at` predates this run — every
    listing the run *did* see was just stamped with `run_started_at`.

    Only the sources this run actually covered are considered, so the
    scheduled run never retires what `scrape-local` collected (or the
    reverse) just by not having looked at it.

    Sources with any failing combo are skipped entirely. A blocked or
    broken source returns nothing, and "saw nothing" must never be read as
    "everything is gone" — that would wipe a whole marketplace from the
    dashboard on a single bad day, and (since retirement is what stops a
    listing being exported) hide it until the site came back.
    """
    retired: dict[str, int] = {}
    with session_scope() as session:
        for source_name in sources:
            if source_name in skip_sources:
                continue
            result = session.execute(
                update(Listing)
                .where(
                    Listing.source == source_name,
                    Listing.is_active.is_(True),
                    Listing.last_seen_at < run_started_at,
                )
                .values(is_active=False)
            )
            if result.rowcount:
                retired[source_name] = result.rowcount
    return retired


def cmd_export(args: argparse.Namespace) -> None:
    """Dump the DB to a static JSON file the frontend can fetch directly.

    Stand-in for Supabase's auto-REST API during local dev (see
    frontend/README) - same listing shape, just a file instead of a live
    query. Only `is_active` listings are included.
    """
    now = utc_now()
    with session_scope() as session:
        latest_observed_at = session.execute(select(func.max(ListingSnapshot.observed_at))).scalar()
        latest_scrape_date = latest_observed_at.date() if latest_observed_at else None

        snapshots_by_listing: dict[str, list[ListingSnapshot]] = defaultdict(list)
        for snapshot in session.execute(select(ListingSnapshot)).scalars():
            snapshots_by_listing[snapshot.listing_id].append(snapshot)

        listings_out = []
        for listing in session.execute(select(Listing).where(Listing.is_active.is_(True))).scalars():
            snapshots = snapshots_by_listing.get(listing.id)
            if not snapshots:
                continue
            latest = max(snapshots, key=lambda s: s.observed_at)
            listings_out.append(
                {
                    "id": listing.id,
                    "source": listing.source,
                    "model": listing.model,
                    "chassisGen": listing.chassis_gen,
                    "variant": listing.variant,
                    "country": listing.country,
                    "modelYear": listing.model_year,
                    "firstRegistration": listing.first_registration.isoformat() if listing.first_registration else None,
                    "url": listing.url,
                    "titleRaw": listing.title_raw,
                    "photoUrls": listing.photo_urls,
                    "sellerType": listing.seller_type,
                    "location": listing.location,
                    "powerKw": listing.power_kw,
                    "color": listing.color,
                    "firstSeenAt": listing.first_seen_at.isoformat(),
                    "priceEur": latest.price_eur,
                    "mileageKm": latest.mileage_km,
                    "daysAtCurrentPrice": days_at_current_price(snapshots, as_of=now),
                    "isNew": is_new_since_last_scrape(listing.first_seen_at, latest_scrape_date=latest_scrape_date)
                    if latest_scrape_date
                    else False,
                }
            )

    payload = {
        "generatedAt": now.isoformat(),
        "latestScrapeDate": latest_scrape_date.isoformat() if latest_scrape_date else None,
        "listings": listings_out,
    }
    # The default target (frontend/public/data/) doesn't exist in a fresh
    # clone: the export is gitignored generated data, and git doesn't track
    # empty directories. Create the path rather than making every caller -
    # CI included - remember to mkdir first.
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"exported {len(listings_out)} active listings to {args.out}")


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
            color=raw.color,
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
        listing.color = raw.color or listing.color

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
    p_scrape.add_argument(
        "--huf-rate", type=float, default=None, help="override the live ECB HUF rate (e.g. for offline testing)"
    )
    p_scrape.add_argument("--max-pages", type=int, default=None, help="cap result pages fetched (default: no cap)")
    p_scrape.set_defaults(func=cmd_scrape)

    p_scrape_all = subparsers.add_parser(
        "scrape-all",
        help="scrape every source the scheduled run can reach (the daily-cron entry point)",
    )
    p_scrape_all.add_argument(
        "--max-pages", type=int, default=None, help="cap result pages fetched per combo (default: no cap)"
    )
    p_scrape_all.add_argument(
        "--include-blocked",
        action="store_true",
        help=f"also try {', '.join(DATACENTER_BLOCKED_SOURCES)} (expected to 403 from a datacenter; use to re-check whether that still holds)",
    )
    p_scrape_all.set_defaults(func=cmd_scrape_all)

    p_scrape_local = subparsers.add_parser(
        "scrape-local",
        help=f"scrape {', '.join(DATACENTER_BLOCKED_SOURCES)} - run from a home connection, these refuse datacenter traffic",
    )
    p_scrape_local.add_argument(
        "--max-pages", type=int, default=None, help="cap result pages fetched per combo (default: no cap)"
    )
    p_scrape_local.set_defaults(func=cmd_scrape_local)

    p_export = subparsers.add_parser("export", help="dump active listings to a static JSON file for the frontend")
    p_export.add_argument("--out", required=True, help="output path, e.g. frontend/public/data/listings.json")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
