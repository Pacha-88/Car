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

**Phase 1 (data model + one source end-to-end): done.** Data model,
chassis/currency normalization, ECB feed parser, CLI (`init-db`, `scrape`,
`tesla-raw-sample`), all unit-tested.

**Phase 2 (all four sources): done.** Every source is verified against a
real response, not guessed — either fetched live from this sandbox, or
(where the sandbox itself is blocked — see below) fetched by the project
owner from a normal connection and fed back in, then checked into
`tests/fixtures/` so the parsing logic stays regression-tested against real
shapes rather than synthetic ones.

| Source | Coverage | How it reads listings | Verified how |
| --- | --- | --- | --- |
| `tesla.py` | any market with a `MARKET_REFERENCE_POINTS` entry (DE/AT/HU) | Tesla's own inventory JSON API | real response the owner fetched and pasted in |
| `autoscout24.py` | DE/AT/NL/BE/IT/ES/FR/LU (confirmed HU is empty — AutoScout24 doesn't meaningfully cover Hungary) | `__NEXT_DATA__` JSON a Next.js page embeds | live fetch + live `car-tracker scrape` run, from this sandbox |
| `kleinanzeigen.py` | DE only | regex over server-rendered `.aditem` cards (no JSON blob, more fragile than the two above) | live fetch from this sandbox, saved as a fixture before the sandbox got rate-limited (see below) |
| `hasznaltauto.py` | HU only | regex over server-rendered listing rows, split on each row's opening tag rather than matched start/end (deeply nested `<div>`s, no unique closing marker) | real response the owner fetched and pasted in |

Two sources needed the field-mapping fixed against reality after being
built from best-effort guesses: Tesla's `parse_item()` had several wrong
field names (the odometer unit field is `OdometerType`/`OdometerTypeShort`,
not the guessed `OdometerTypeUnit`; there's no `VehicleConfig` wrapper) and
was missing `first_registration` (hardcoded `None`), real photo URLs
(guessed empty, `VehiclePhotos` has them directly) and `color` (`PAINT`).
The variant-bucketing heuristic (`normalize/variant.py`) also had a real bug
caught by Használtautó.hu data: a title stating "Long Range AWD" up front
but mentioning "Performance" later as a cosmetic package name was
misclassified, because the original heuristic checked for "performance"
unconditionally before anything else — fixed to leftmost-keyword-wins.

Also picked up `power_kw` and `color` along the way (neither was in the
original schema, both turned out to be readily available) — see
`docs/DASHBOARD_SPEC.md`.

**Known gap — this development sandbox's own network limits:** Tesla.com
and Használtautó.hu both block this sandbox's outbound requests at the site
level regardless of org network policy — Tesla via Akamai (403s even a
plain homepage GET, likely IP-reputation-based), Használtautó.hu via
Cloudflare Bot Management. A real-browser-fingerprint test (Playwright/
Chromium) to see if that fares better was inconclusive: this sandbox's
Chromium can't complete a trusted HTTPS connection to *any* external host
yet (confirmed against pypi.org too, fully allowlisted) — a gap in the
sandbox's own proxy/CA plumbing for browser engines, not something to paper
over with `--ignore-certificate-errors`. Both sources got unblocked by
fetching from the owner's normal home connection instead.

Kleinanzeigen's search pages *were* open to this sandbox at first — two
working live fetches — but a handful of requests in, its own anti-abuse
system returned a temporary "IP-Bereich gesperrt" (IP-range blocked) page,
unprompted by anything beyond ordinary exploratory probing. That's why
`kleinanzeigen.py`'s `REQUEST_DELAY_SECONDS` is more conservative than
`autoscout24.py`'s and `hasznaltauto.py`'s — a starting point to tune, not
a guarantee it's enough. Whatever runs any of these for real should expect
this class of block to recur if hit too hard, and go easy on it — none of
this sandbox's findings about *which* sources are more or less sensitive
should be read as settled; they're one afternoon's data point each.

**Also confirmed, not yet acted on:** battery SoH (State of Health) shows up
as free text on both Kleinanzeigen and Használtautó.hu titles/descriptions
(e.g. "91,8 SOH", "SOH: 95.5%") — real and not rare, but formatting isn't
consistent enough from a couple of examples to extract with confidence; see
`docs/DASHBOARD_SPEC.md`.

Not started: analysis layer (Phase 3), dashboard (Phase 4), deployment (Phase 5).

## Running it

```
uv run pytest                 # unit tests, no network needed
uv run car-tracker init-db    # creates car_tracker.db (SQLite) in the cwd
uv run car-tracker tesla-raw-sample --model model_y --country DE   # needs network
uv run car-tracker scrape --source tesla --model model_y --country DE --huf-rate 0.00256  # needs network
uv run car-tracker scrape --source autoscout24 --model model_y --country AT --max-pages 2  # works today
uv run car-tracker scrape --source kleinanzeigen --model model_y --country DE --max-pages 1  # works, but go easy on it (see README)
uv run car-tracker scrape --source hasznaltauto --model model_y --country HU --max-pages 1  # needs network (blocked from this sandbox)
```
