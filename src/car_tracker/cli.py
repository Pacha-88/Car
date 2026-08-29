"""Command-line entry points for running scrapes and inspecting sources."""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from car_tracker.analysis.listing_status import days_at_current_price, is_new_since_last_scrape
from car_tracker.db.models import FxRate, Listing, ListingSnapshot
from car_tracker.db.session import init_db, session_scope
from car_tracker.fx.ecb import fetch_latest_rates
from car_tracker.normalize.chassis import detect_chassis
from car_tracker.normalize.currency import EUR, market_currency, to_eur
from car_tracker.normalize.registration import plausible_registration
from car_tracker.normalize.title import ensure_title
from car_tracker.normalize.variant import normalize_variant
from car_tracker.sources.autoscout24 import COUNTRY_CODES as AUTOSCOUT24_COUNTRIES
from car_tracker.sources.autoscout24 import AutoScout24Source
from car_tracker.sources.base import PartialResults, RawListing
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

# Gap between one source/model/country combo and the next.
COMBO_DELAY_SECONDS = 3.0


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
    rate_date, ecb_rates, rates_from = _resolve_rates()
    rates_to_eur = {EUR: 1.0, **ecb_rates}
    if rates_from == "live":
        print(f"fx rates as of {rate_date} (HUF={rates_to_eur.get('HUF')})")
        try:
            _store_rates(rate_date, ecb_rates)
        except Exception as exc:  # noqa: BLE001
            # Belt and braces behind the retry above. This run already holds
            # the rates it needs in memory; storing them only lets the
            # *export* convert to forints later. Losing that is one number
            # on the dashboard falling back to euros - not a reason to throw
            # away a whole morning's prices before a single car is fetched.
            print(f"warning: could not store fx rates ({type(exc).__name__}: {exc}) - scraping anyway")
    elif rates_from == "stored":
        print(f"warning: ECB unreachable - using stored rates from {rate_date} (HUF={rates_to_eur.get('HUF')})")
    else:
        print("warning: ECB unreachable and no stored rates - EUR-priced listings only this run")

    now = utc_now()
    total_stored = 0
    failures: list[str] = []
    partials: list[str] = []
    failed_sources: set[str] = set()
    # Sources whose picture of the market this run is missing part of -
    # whether a combo failed outright or only came back half-fetched. Both
    # mean the same thing for retirement: "not seen" is not "sold".
    incomplete_sources: set[str] = set()
    stored_per_source: dict[str, int] = {}

    first_combo = True
    for source_name, target in targets.items():
        source_cls = SOURCES[source_name]
        for model in target["models"]:
            for country in target["countries"]:
                combo = f"{source_name}/{model}/{country}"
                # Pace the combos themselves, not just the pages within one.
                # Each combo opens a fresh client, so per-source page delays
                # don't span the gap between them - and six Tesla markets
                # back to back is exactly the burst that drew HTTP 429s.
                if not first_combo:
                    time.sleep(COMBO_DELAY_SECONDS)
                first_combo = False
                partial_reason: str | None = None
                try:
                    with source_cls() as source:
                        try:
                            raw_listings = source.fetch_listings(model=model, country=country, max_pages=max_pages)
                        except PartialResults as partial:
                            raw_listings, partial_reason = partial.listings, partial.reason
                    with session_scope() as session:
                        for raw in raw_listings:
                            _upsert(session, raw, rates_to_eur=rates_to_eur, observed_at=now)
                    total_stored += len(raw_listings)
                    stored_per_source[source_name] = stored_per_source.get(source_name, 0) + len(raw_listings)
                    if partial_reason is None:
                        print(f"ok    {combo}: {len(raw_listings)} listings")
                    else:
                        # Stored, but deliberately not treated as a clean run:
                        # the cars on the pages we never fetched are unseen,
                        # not gone, so this source retires nothing this time.
                        print(f"partial {combo}: kept {len(raw_listings)} listings, but {partial_reason}")
                        partials.append(combo)
                        incomplete_sources.add(source_name)
                except Exception as exc:  # noqa: BLE001 - one combo's failure must not abort the rest
                    print(f"FAILED {combo}: {exc}")
                    failures.append(combo)
                    failed_sources.add(source_name)
                    incomplete_sources.add(source_name)

    retired = _retire_unseen(now, sources=targets, skip_sources=incomplete_sources)
    for source_name, count in sorted(retired.items()):
        print(f"retired {source_name}: {count} listing(s) no longer on the site")
    for source_name in sorted(incomplete_sources):
        why = "failing" if source_name in failed_sources else "incomplete"
        print(f"kept    {source_name}: not retiring anything, this source had {why} combo(s) this run")

    # A per-source verdict, because "0 listings stored" across a mixed run
    # doesn't say which site worked - and this is read by someone watching a
    # browser window open and close, not by someone reading a stack trace.
    for source_name in targets:
        got = stored_per_source.get(source_name, 0)
        if source_name in failed_sources and got == 0:
            print(f"  {source_name}: NO data (every attempt was refused)")
        elif source_name in failed_sources:
            print(f"  {source_name}: {got} listings (some attempts were refused)")
        else:
            print(f"  {source_name}: {got} listings")

    partial_note = f", {len(partials)} partial" if partials else ""
    print(
        f"{label} done: {total_stored} listings stored across {len(targets)} sources, "
        f"{len(failures)} combo(s) failed{partial_note}"
    )
    if partials:
        # Worth saying out loud, but not worth failing the run over: a
        # partial combo still stored real, current prices.
        print(f"partial combos: {', '.join(partials)}")
    if failures:
        raise SystemExit(f"failed combos: {', '.join(failures)}")


def _resolve_rates() -> tuple[date | None, dict[str, float], str]:
    """Today's rates if the ECB answers, yesterday's stored ones if not.

    fetch_latest_rates() used to sit unguarded at the top of _run_scrape,
    which made one ECB timeout kill the entire nightly run before a single
    car was fetched - even though nearly every listing is EUR-priced and
    needs no rate at all, and the fx_rates table already holds the last
    run's numbers (daily reference rates move fractions of a percent, so
    yesterday's rate is a fine way to price a used car).

    Last resort is no rates at all: EUR listings convert trivially, and a
    non-EUR combo then fails inside its own try in the scrape loop - which
    marks that source failed and, crucially, exempts it from retirement,
    exactly as if the site itself had been down.
    """
    try:
        rate_date, ecb_rates = fetch_latest_rates()
        return rate_date, ecb_rates, "live"
    except Exception:  # noqa: BLE001 - any fetch failure means "try the stored ones"
        pass
    try:
        with session_scope() as session:
            latest = session.execute(select(func.max(FxRate.rate_date))).scalar()
            if latest is not None:
                rows = session.execute(select(FxRate).where(FxRate.rate_date == latest)).scalars()
                return latest, {row.currency: row.rate_to_eur for row in rows}, "stored"
    except Exception:  # noqa: BLE001 - a DB hiccup here must not outrank the scrape itself
        pass
    return None, {}, "none"


def _store_rates(rate_date: date, rates_to_eur: dict[str, float]) -> None:
    """Keep the day's rates, so the export doesn't need the ECB itself.

    The export runs right after a scrape and could refetch, but then a
    minute of ECB downtime would cost the whole dashboard rather than one
    number - and the rates a run *used* are the ones its prices should be
    read back with.

    Two runs write here at once. The scheduled GitHub run and the
    `scrape-local` cron both aim at the same morning and the same database,
    and they store the *same* rates under the same (date, currency) key -
    so "does the row exist yet" answered before either has committed sends
    both down the insert path and one of them into a duplicate-key error.
    Measured with the two runs starting together: 11 collisions in 12
    attempts, which is not a rare race, it is the normal outcome. On the
    retry every row exists, so it is pure updates and cannot collide again.
    """
    for attempt in (1, 2):
        try:
            with session_scope() as session:
                for currency, rate in rates_to_eur.items():
                    existing = session.get(FxRate, (rate_date, currency))
                    if existing is None:
                        session.add(FxRate(rate_date=rate_date, currency=currency, rate_to_eur=rate))
                    else:
                        existing.rate_to_eur = rate
            return
        except IntegrityError:
            if attempt == 2:
                raise
            # The other run committed the same ECB numbers between our read
            # and our write. Nothing is lost - go round once more and update.


def _latest_huf_per_eur(session) -> float | None:
    """How many forints one euro buys, from the most recent stored rate.

    Everything is stored in EUR (prices come from six countries), but the
    person reading this dashboard is shopping in Hungary and thinks in
    millions of forints. Returns None when no rate has ever been stored, in
    which case the dashboard simply stays in euros rather than inventing a
    conversion.
    """
    row = session.execute(
        select(FxRate.rate_to_eur)
        .where(FxRate.currency == "HUF")
        .order_by(FxRate.rate_date.desc())
        .limit(1)
    ).scalar()
    # Stored as "1 HUF = x EUR"; the dashboard wants the other direction.
    return round(1 / row, 4) if row else None


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


# The last line of defence for retirement. Every guard above keys off a
# source *reporting* trouble — but the worst failures are the quiet ones: a
# throttle page served with HTTP 200 and no ads on it, a markup change that
# suddenly matches nothing, a site answering with an empty result set. Those
# all look like a perfectly successful scrape that happened to find no cars,
# and would retire an entire marketplace.
#
# Used cars do not all sell overnight. A run that wants to retire more than
# half of a source's active listings is describing an event that doesn't
# happen, so refuse it and say so loudly rather than quietly emptying the
# dashboard. The listings stay active and get picked up again by the next
# healthy run, which reactivates anything it sees.
MAX_RETIREMENT_SHARE = 0.5

# Below this many active listings the share is noise, not signal — a market
# with three cars in it can legitimately lose two in a day. The cap only
# applies once a source is big enough for percentages to mean something.
MIN_ACTIVE_FOR_RETIREMENT_CAP = 10

# ...and the cap needs a way out, or it stops being a safety net and
# becomes a leak. Refusing on its own is permanent: the same implausible
# gap is refused again the next day, and the next, so a source that really
# did shrink — or that this project simply stopped scraping a country of —
# would keep its dead listings on the dashboard forever. Measured: ten runs
# against a market that fell from 400 cars to 20 retired nothing at all.
#
# A listing nobody has found for a week is not a blip either way. Either
# the car is gone, or the source has been broken for a week and its prices
# are a week stale — and a week-old price shown as today's is its own kind
# of wrong. So the cap delays retirement rather than vetoing it: past this
# many days, unseen listings go regardless of how many there are.
STALE_AFTER_DAYS = 7


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

    Sources with any failing or incomplete combo are skipped entirely. A
    blocked or broken source returns nothing, and "saw nothing" must never
    be read as "everything is gone" — that would wipe a whole marketplace
    from the dashboard on a single bad day, and (since retirement is what
    stops a listing being exported) hide it until the site came back.

    On top of that, MAX_RETIREMENT_SHARE refuses any implausibly large
    retirement even when every combo reported success — see below.
    """
    retirable = [name for name in sources if name not in skip_sources]
    if not retirable:
        # Every source failed, so there is nothing to retire. Return before
        # opening a connection: a run where every site was blocked should
        # not also need a working database to finish reporting that.
        return {}

    retired: dict[str, int] = {}
    with session_scope() as session:
        for source_name in retirable:
            unseen_where = (
                Listing.source == source_name,
                Listing.is_active.is_(True),
                Listing.last_seen_at < run_started_at,
            )
            active = session.execute(
                select(func.count()).select_from(Listing).where(Listing.source == source_name, Listing.is_active.is_(True))
            ).scalar_one()
            unseen = session.execute(select(func.count()).select_from(Listing).where(*unseen_where)).scalar_one()
            if not unseen:
                continue
            if active >= MIN_ACTIVE_FOR_RETIREMENT_CAP and unseen / active > MAX_RETIREMENT_SHARE:
                # Too many at once to believe today — but not forever (see
                # STALE_AFTER_DAYS): whatever has been missing for a week
                # goes anyway, so a real shrink still drains and a broken
                # source can't hold stale prices on the dashboard for good.
                stale_where = (*unseen_where, Listing.last_seen_at < run_started_at - timedelta(days=STALE_AFTER_DAYS))
                stale = session.execute(select(func.count()).select_from(Listing).where(*stale_where)).scalar_one()
                print(
                    f"kept    {source_name}: would have retired {unseen} of {active} active listings "
                    f"({unseen / active:.0%}) - refusing, that is a broken scrape, not a sold-out market"
                    + (
                        f" (retiring {stale} of them anyway - unseen for over {STALE_AFTER_DAYS} days)"
                        if stale
                        else ""
                    )
                )
                if stale:
                    session.execute(update(Listing).where(*stale_where).values(is_active=False))
                    retired[source_name] = stale
                continue
            session.execute(update(Listing).where(*unseen_where).values(is_active=False))
            retired[source_name] = unseen
    return retired


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
        huf_per_eur = _latest_huf_per_eur(session)

        snapshots_by_listing: dict[str, list[ListingSnapshot]] = defaultdict(list)
        for snapshot in session.execute(select(ListingSnapshot)).scalars():
            snapshots_by_listing[snapshot.listing_id].append(snapshot)

        listings_out = []
        for listing in session.execute(select(Listing).where(Listing.is_active.is_(True))).scalars():
            snapshots = snapshots_by_listing.get(listing.id)
            if not snapshots:
                continue
            latest = max(snapshots, key=lambda s: s.observed_at)
            if not is_plausible_car(latest.price_eur):
                continue
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
        # Prices are stored in EUR; this lets the dashboard show them in
        # forints without every listing carrying a converted copy that
        # would go stale the moment the rate moved.
        "hufPerEur": huf_per_eur,
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
    # Before anything reads the date: a slipped digit ("12/2002" for a Model
    # Y) is a normal marketplace typo, and chassis detection, the year
    # filter and the depreciation curve all take it at face value.
    first_registration, model_year = plausible_registration(
        raw.model, first_registration=raw.first_registration, model_year=raw.model_year
    )
    chassis_gen = detect_chassis(
        raw.model, first_registration=first_registration, model_year=model_year, title=raw.title_raw
    )
    variant = normalize_variant(raw.variant)
    # Belt and braces across all four sources: whatever the parsers manage,
    # a card must never render as "Untitled".
    fallback_title = ensure_title(None, model=raw.model)

    if listing is None:
        listing = Listing(
            id=listing_id,
            source=raw.source,
            source_listing_id=raw.source_listing_id,
            model=raw.model,
            chassis_gen=chassis_gen,
            variant=variant,
            country=raw.country,
            model_year=model_year,
            first_registration=first_registration,
            url=raw.url,
            title_raw=raw.title_raw or fallback_title,
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
        # Refresh descriptive fields, `or` so a scrape that happens to come
        # back thin never blanks out good data we already hold.
        #
        # This is not just an optimisation. A listing is only written in
        # full the very first time it is seen, so any field that was missing
        # or wrong then stayed that way for the life of the listing, however
        # many times it was scraped afterwards. That is how every Tesla
        # already in the database kept reading "Untitled" (this source used
        # to store no title at all) and why a listing first seen without
        # photos never got one: fixing the source alone would only have
        # helped cars first listed after the fix.
        listing.chassis_gen = chassis_gen or listing.chassis_gen
        listing.variant = variant or listing.variant
        listing.power_kw = raw.power_kw or listing.power_kw
        listing.color = raw.color or listing.color
        listing.title_raw = raw.title_raw or listing.title_raw or fallback_title
        listing.photo_urls = raw.photo_urls or listing.photo_urls
        listing.location = raw.location or listing.location
        listing.url = raw.url or listing.url
        # Not `or`: when the source does say something about the date, its
        # answer wins outright - including "what it gave is not believable",
        # which has to clear a bad stored value rather than preserve it
        # forever. Only silence from the source leaves what we already hold.
        if raw.first_registration is not None or raw.model_year is not None:
            listing.first_registration = first_registration
            listing.model_year = model_year
        listing.seller_type = raw.seller_type or listing.seller_type

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
