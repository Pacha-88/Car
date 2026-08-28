# car-tracker

Daily price-tracking dashboard for used Tesla Model Y / Model 3 listings
across DE / AT / HU / rest-of-EU, aggregated from multiple sources
(Tesla.com, AutoScout24, Kleinanzeigen, Használtautó.hu, +1 TBD), with real
price-change history (not just daily snapshots), a depreciation-by-model-year
module, and an interactive dashboard.

## Architecture

- **Scraping** (Python): one module per source under `src/car_tracker/sources/`,
  each producing `RawListing` objects (see `sources/base.py`) — normalization
  and storage are shared, so adding a source never means re-implementing those.
- **Storage**: SQLAlchemy models (`src/car_tracker/db/models.py`), SQLite for
  local dev, Postgres/Supabase in production. Snapshot-based history:
  `listings` holds identity, `listing_snapshots` gets one row per scrape per
  listing — price-change history, "days at this price" and "new since last
  scrape" are all derived from that table rather than tracked separately.
- **Normalization**: currency conversion to EUR (`normalize/currency.py`,
  daily rates from the ECB via `fx/ecb.py`) and chassis-generation detection
  — Model 3's refresh is codenamed "Highland", Model Y's is "Juniper", both
  vs. "Legacy" pre-refresh (`normalize/chassis.py`).
- **Frontend** (not started yet): React, reading from Supabase directly
  (its free tier includes an auto-generated REST API, so no custom backend
  server is needed).
- **Scheduling** (not started yet): GitHub Actions cron, daily.

## Status

**Phase 1 (data model + one source end-to-end): done**, except the Tesla
source itself — see gap below. Data model, chassis/currency normalization,
ECB feed parser, CLI (`init-db`, `scrape`, `tesla-raw-sample`), all unit-tested.

**Phase 2 (more sources): in progress.** AutoScout24 is done and verified end
to end against live data — `parse_item()` reads the `__NEXT_DATA__` JSON
Next.js embeds in the search-results page (not HTML scraping), tested against
real fixture data (`tests/fixtures/autoscout24_search_sample.html`) and via a
live `car-tracker scrape` run. Covers DE/AT/NL/BE/IT/ES/FR/LU — confirmed HU
returns zero results (AutoScout24 doesn't meaningfully cover Hungary, which
is why Használtautó.hu is a separate source rather than redundant). Also
picked up `power_kw` along the way (in `vehicleDetails`, wasn't in the
original schema) — see `docs/DASHBOARD_SPEC.md`. Not started: Kleinanzeigen,
Használtautó.hu.

**Known gap:** the Tesla source's `parse_item()` is still an unverified
best-effort guess — this sandbox's network policy now allows tesla.com, but
Tesla's own Akamai edge 403s even a plain homepage GET from here, likely
IP-reputation-based. A real-browser-fingerprint test (Playwright/Chromium)
was inconclusive: this sandbox's Chromium can't complete a trusted HTTPS
connection to *any* external host yet (confirmed against pypi.org too,
which is fully allowlisted) — a gap in the sandbox's own proxy/CA plumbing
for browser engines, separate from both the org policy and Tesla's block,
and not something to paper over with `--ignore-certificate-errors`.
Használtautó.hu hits the same wall (Cloudflare Bot Management 403s its
homepage too). Options, still open:

1. Fetch from your own network (`curl`/browser) and paste the response back.
2. Do the scraper-verification steps from a local Claude Code session instead.
3. A residential/anti-bot-proxy service for whichever of these stay blocked
   even from a normal home network (not yet needed — untested from one).

Not started: analysis layer (Phase 3), dashboard (Phase 4), deployment (Phase 5).

## Running it

```
uv run pytest                 # unit tests, no network needed
uv run car-tracker init-db    # creates car_tracker.db (SQLite) in the cwd
uv run car-tracker tesla-raw-sample --model model_y --country DE   # needs network
uv run car-tracker scrape --source tesla --model model_y --country DE --huf-rate 0.00256  # needs network
uv run car-tracker scrape --source autoscout24 --model model_y --country AT --max-pages 2  # works today
```
