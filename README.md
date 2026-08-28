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

## Status — Phase 1 (data model + one source end-to-end)

Done: data model, chassis/currency normalization (unit-tested), ECB feed
parser (unit-tested against a sample response), Tesla.com source scaffolding
(request/pagination), CLI (`init-db`, `scrape`, `tesla-raw-sample`).

**Known gap:** the Tesla source's `parse_item()` (field-name mapping off a
raw inventory result) is a best-effort guess, not yet checked against a real
response — this development sandbox's network policy blocks outbound
requests to tesla.com (and likely every other listing site). Everything that
doesn't need live network (models, normalization, tests) is verified; the
scraping HTTP calls are not, yet. Options to unblock, still open:

1. Allow the relevant domains in this environment's network policy and continue here.
2. Keep developing here, verify by running `tesla-raw-sample` locally / wherever network is open and feeding the output back.
3. Do the scraper-verification steps from a local Claude Code session instead.

Not started: AutoScout24 / Kleinanzeigen / Használtautó.hu sources (Phase 2),
analysis layer (Phase 3), dashboard (Phase 4), deployment (Phase 5).

## Running it

```
uv run pytest                 # unit tests, no network needed
uv run car-tracker init-db    # creates car_tracker.db (SQLite) in the cwd
uv run car-tracker tesla-raw-sample --model model_y --country DE   # needs network
uv run car-tracker scrape --source tesla --model model_y --country DE --huf-rate 0.00256  # needs network
```
