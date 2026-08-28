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
- **Frontend** (`frontend/`): Vite + React 19 + TypeScript + Tailwind v4 +
  Recharts, reading a static `car-tracker export` JSON snapshot
  (`frontend/public/data/listings.json`, gitignored — regenerate after every
  scrape). Trend and depreciation math (`src/lib/trend.ts`,
  `src/lib/depreciation.ts`) are direct TypeScript ports of the Python
  analysis layer, computed client-side so filtering recomputes instantly —
  Supabase (Phase 5) has no compute layer of its own, so this stays
  client-side even after the backend moves off flat files.
- **Scheduling**: GitHub Actions cron, daily
  (`.github/workflows/scrape-and-deploy.yml`) — runs `scrape-all`, exports,
  builds the frontend, deploys to GitHub Pages. Needs a few one-time manual
  setup steps before it's actually live; see `docs/DEPLOYMENT.md`.

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

**Phase 3 (analysis layer): done, with reasonable defaults flagged for
later tuning rather than settled decisions.** `src/car_tracker/analysis/`:

- `listing_status.py` — `days_at_current_price` (walks a listing's
  snapshots back from the latest while the price is unchanged) and
  `is_new_since_last_scrape` (compares `first_seen_at`'s date against the
  most recent scrape date). Both derive straight from the snapshot table,
  no design ambiguity here.
- `trend.py` — a binned-median trend line for the scatter chart, and a
  plain closed-form linear (OLS) slope for the "€ per 10k km" stat and for
  mileage-normalizing prices in the depreciation module. Deliberately not
  LOESS/polynomial: no stats dependency needed, robust to the outlier
  listings every source has, and the binned-median approach visually
  approximates the curved trend line in the reference screenshots without
  a real risk of overfitting at the sparse ends of the mileage range.
- `depreciation.py` — age-bucketing (whole years, `under_1yr`/`1yr`/.../
  `7yr_plus` catch-all), the `reference_km=60_000` / `min_bucket_size=10`
  defaults matching the numbers implied by the reference screenshots, and
  the `steepest_drop`/`curve_flattens_at`/`cheapest_to_own` insight cards.
  **Not implemented: "versus buying new" and a true "new list price"
  reference point** — both need Tesla's *new*-car pricing, which none of
  the four sources (all used-listing sources) provide; faking a stand-in
  felt worse than leaving the gap documented.

Verified against real pooled data from all four sources' fixtures (10
listings): produced a plausible slope (~‑640 EUR per 10k km) and sensible
buckets, correctly flagging every bucket thin at this tiny sample size —
real depreciation numbers need real scrape volume, which this doesn't have
yet (Phase 5).

**Phase 4 (dashboard): done.** `frontend/` — model switcher (Model Y / Model
3), full filter bar (country incl. rest-of-EU grouping, marketplace, seller
type, variant, chassis generation, colour, year/price/mileage range sliders,
"new since last scrape" and watchlist-only toggles), price-vs-mileage
scatter chart with a binned-median trend line and per-listing hover cards
("held at this price for N days"), a depreciation-by-model-year module with
the `steepest_drop`/`curve_flattens_at`/`cheapest_to_own` insight cards from
Phase 3, and a sortable/paginated listing grid with photos and a
localStorage-backed watchlist. Dark/light theming throughout, built to the
`dataviz` skill's palette/contrast/mark-spec rules.

Verified with a real (non-mocked) pooled export — 342 Model Y listings
across all four sources — driven headlessly with Playwright: chart, filters,
depreciation insights and grid all render correctly against real computed
numbers. Two real issues surfaced this way and got fixed: filter chips'
active state initially had too little contrast against inactive ones
(fixed in `Chip.tsx` — solid fill instead of a 15%-opacity tint), and a
stray `/favicon.ico` 404 (fixed by inlining an SVG data-URI icon in
`index.html` rather than shipping a binary asset). All other console
errors seen in this sandbox are external listing-photo CDNs
(`autoscout24.net`, `hasznaltautocdn.com`, `tesla.com`, `kleinanzeigen.de`)
being unreachable from here — the same class of network restriction noted
throughout Phase 2, not an app bug; the `onError` fallback hides the broken
`<img>` cleanly (a plain placeholder box, no broken-image icon) so this is
just a something-to-expect-in-this-sandbox note, not a real-deployment
concern.

Every listing in the current demo export shows a "NEW" badge — expected,
not a bug: all of it came from a single scrape batch with no prior scrape
to diff against, and "new" is defined relative to the previous scrape date.

**Phase 5 (deployment): code-ready, three manual one-time steps left —
see `docs/DEPLOYMENT.md`.** `db/session.py` already accepted a
`DATABASE_URL` override from Phase 1 (`postgresql+psycopg://...`); this
phase added the driver (`psycopg[binary]`), a `car-tracker scrape-all`
command that runs every source/model/country combo the project tracks in
one go (best-effort per combo — one source failing doesn't stop the
others, but every failure is still surfaced, non-zero exit at the end),
wired live ECB rates into both `scrape` and `scrape-all` (no more manual
`--huf-rate` in production), and `.github/workflows/scrape-and-deploy.yml`
— daily cron: scrape, export, build the frontend, deploy to GitHub Pages.

Verified for real, not assumed: the full pipeline end-to-end against an
actual local PostgreSQL 16 instance (schema, upsert-then-new-snapshot
behavior, the works — see `docs/DEPLOYMENT.md`), `scrape-all` against
every real combo (AutoScout24 + Kleinanzeigen succeeded; Tesla and
Használtautó.hu 403'd, which is why the workflow tolerates partial
failure rather than aborting the whole day's deploy over it), the ECB
feed live for the first time this phase, and the production frontend
build served from a simulated GitHub Pages subpath.

What's left is three steps only the project owner can do (an external
Supabase signup, a repo secret, a repo settings toggle) — all spelled out
in `docs/DEPLOYMENT.md`.

## Running it

```
uv run pytest                 # unit tests, no network needed
uv run car-tracker init-db    # creates car_tracker.db (SQLite) in the cwd
uv run car-tracker tesla-raw-sample --model model_y --country DE   # needs network
uv run car-tracker scrape --source tesla --model model_y --country DE --huf-rate 0.00256  # needs network
uv run car-tracker scrape --source autoscout24 --model model_y --country AT --max-pages 2  # works today
uv run car-tracker scrape --source kleinanzeigen --model model_y --country DE --max-pages 1  # works, but go easy on it (see README)
uv run car-tracker scrape --source hasznaltauto --model model_y --country HU --max-pages 1  # needs network (blocked from this sandbox)
uv run car-tracker scrape-all --max-pages 1   # every source/model/country combo in one go — what the daily workflow runs
uv run car-tracker export --out frontend/public/data/listings.json         # dumps active listings for the dashboard
```

Point `DATABASE_URL` (env var) at a `postgresql+psycopg://...` connection
string to run any of the above against Postgres instead of the local SQLite
default — no code changes needed, `init-db`/`scrape`/`export` all read it
the same way.

Then, in `frontend/`:

```
npm install
npm run dev    # dashboard at http://localhost:5173
```
