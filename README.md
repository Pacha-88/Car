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
response. The environment's network policy has since been opened up to the
source domains, which unblocked some but not all of them — current picture
(2026-08-28, from this sandbox's outbound IP):

| Source | Org network policy | Site's own bot defense |
| --- | --- | --- |
| tesla.com | allowed | **blocked** — Akamai 403s even the plain homepage, likely IP-reputation-based |
| autoscout24.com | allowed | open — a real search-results page (`/lst/tesla/model-y`) fetched fine with plain `httpx`/no special handling |
| kleinanzeigen.de | allowed | homepage open; search/listing pages not tested yet |
| hasznaltauto.hu | allowed | **blocked** — Cloudflare Bot Management 403s the homepage |
| ecb.europa.eu | **not allowed yet** — the environment's allowlist has `ecb.europa.eu` but the code requests `www.ecb.europa.eu`, a different host; add `www.ecb.europa.eu` (or `*.ecb.europa.eu`) | untested (never reached) |

Also tried: a real headless-browser fingerprint (Playwright/Chromium, to see
if that gets past Tesla's Akamai block, since that's the standard fix for
this class of problem) — inconclusive, because this sandbox's Chromium can't
complete a trusted HTTPS connection to *any* external host yet, including
ones fully on the allowlist (confirmed against pypi.org too). That's a gap
in the sandbox's own proxy/CA plumbing for browser engines specifically,
separate from both the org policy and Tesla's block, and not something to
paper over with `--ignore-certificate-errors`.

Net effect: AutoScout24 (and probably Kleinanzeigen) can likely be scraped
directly from this sandbox with plain HTTP once Phase 2 gets there. Tesla.com
and Használtautó.hu need verification from a real (non-datacenter) network —
options still open:

1. Fetch from your own network (`curl`/browser) and paste the response back.
2. Do the scraper-verification steps from a local Claude Code session instead.
3. A residential/anti-bot-proxy service for the sources that stay blocked
   even from a normal home network (not yet needed — untested from one).

Not started: AutoScout24 / Kleinanzeigen / Használtautó.hu sources (Phase 2),
analysis layer (Phase 3), dashboard (Phase 4), deployment (Phase 5).

## Running it

```
uv run pytest                 # unit tests, no network needed
uv run car-tracker init-db    # creates car_tracker.db (SQLite) in the cwd
uv run car-tracker tesla-raw-sample --model model_y --country DE   # needs network
uv run car-tracker scrape --source tesla --model model_y --country DE --huf-rate 0.00256  # needs network
```
