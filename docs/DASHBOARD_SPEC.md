# Dashboard UI spec (derived from reference screenshots/video)

Source: screenshots from the creator's original personal tool (video walkthrough
shared 2026-08-28). This was the target look/behavior for Phase 4 (built,
see "Resolved in Phase 4" below for what shipped as-is vs. simplified).
Everything below is observed from those screenshots, not invented.

## Model switcher
Two tabs top-left: **Model Y** / **Model 3**. Switching re-scopes everything
below (stats, chart, depreciation module, grid) to that model.

## Header stat tiles (top-right, recompute live as filters change)
Listings count · Median price · Median mileage · Price per 10k km (the trend
line's local slope — a "what does 10k more km cost you" figure). A tile past
the right edge is cut off in the screenshot — there may be a 5th.

## Title block
- Scope line: "GERMANY · AUSTRIA · HUNGARY — USED MARKET"
- Chart title: "{Model} — price vs mileage"
- One-line caption under the title stating what's plotted, the color
  encoding, today's FX rate used for HUF conversion, and the hover/click hint.
  e.g. "Each point is a listing, coloured by registration year. Hungarian
  prices converted to EUR at 376.07 HUF/€. Hover for detail, click to open
  the ad."

## Filter bar
One shared filter state drives the stat tiles, scatter chart, depreciation
module, and listing grid simultaneously. Groups (all pill/chip toggles unless
noted), roughly:

- **COUNTRY** — Germany / Austria / Hungary / Rest of EU (flag icons)
- **MARKETPLACE** — AutoScout24 / Kleinanzeigen / Használtautó.hu / Tesla.com,
  each with a small colour swatch that's reused as the source-dot badge on
  grid cards
- **SELLER** — Dealer / Private
- **VARIANT** — Long Range AWD / Performance / RWD / Other
- **CHASSIS** — Juniper / Legacy / Unknown
- **COLOUR** — White / Black / Grey / Silver / Blue / Red / Other / Unknown
  (colour dot bullet per option)
- **YEAR** range slider (registration year)
- **PRICE** range slider (€)
- **MILEAGE** range slider (km)
- **HIGHLIGHT** — chips with live counts, function as filters too: "New
  since last scrape N" (orange dot), "Watchlist N" (violet dot)
- Toggles: **Trend line** on/off, **Show excluded listings** on/off
  (statistically-excluded listings — thin data / outliers — are a first-class
  flag, not just a depreciation-chart concept)
- **Reset filters** button

## Scatter chart
X = mileage (km), Y = asking price (€). One point per listing, coloured by
registration year (categorical, ~6 colours, "REG. YEAR" legend top-right of
the chart). Dashed trend line overlaid — curved, so likely a local/LOESS-style
regression rather than a straight OLS fit. A couple of points render with a
highlight ring (selected/watchlisted).

**Hover card** (floats near the point):
- Small badge: registration year/month (e.g. "2025/12")
- Photo
- Ad title (raw)
- Truncated description snippet
- Price, mileage
- Country flag + power (kW)
- **"held €X for N days"** — the price-duration feature: how long the listing
  has sat at its current price. This is the whole reason snapshots aren't
  just overwritten (see listing_snapshots in the data model).
- Pills: source, seller type, variant, chassis
- "Open ad" → external link to the original listing

Click on a point → opens the original ad.

## Depreciation-by-model-year module
Header: "Depreciation by model year". Subtitle states n listings and the
normalization method, e.g. "589 listings · all prices adjusted to 60.000 km
at €68 per 1,000 km" — every listing's price is normalized to one reference
mileage (via a €/1000km slope, presumably read off the trend line) before
bucketing by age, so mileage spread doesn't distort the age comparison.

- Variant sub-tabs: All variants / Long Range AWD / RWD / Performance
- **COMPARE AT** slider — the reference mileage used for normalization
- Main chart: X = age bucket (new list price, under 1yr, 1yr, 2yr, 3yr, 4yr,
  5yr, …) labelled with calendar year + `n=` sample size; Y = normalized
  price. Price label above each point, `% of new list price` below it.
  Shaded confidence band around the line. Buckets with thin data (roughly
  n<10 here) are drawn dashed and explicitly excluded from every derived
  stat — called out in the footnote.
- Right-side auto-computed insight cards:
  - **Cheapest to own** (over N years) — which age to buy at, effective €/yr
  - **Versus buying new** — €/yr and multiplier vs. a 2-year-old
  - **Steepest drop** — which year→year transition loses the most value
  - **Curve flattens** — which transition is cheapest (where it levels off)
  - **Cost of one more year** — bar-style €-per-transition breakdown
- Footnote (worth preserving near-verbatim — sets the tone for statistical
  honesty throughout the tool):
  > Percentages are the figure above each point divided by today's list
  > price — so they move with the mileage slider, and are not what the first
  > owner paid. Tesla has cut new prices repeatedly, so a 2022 car listed far
  > higher when it was new and its real depreciation is worse than shown.
  > This also compares different cars on one day rather than tracking one
  > over time, and these are asking prices, not sale prices. Thin: 2026
  > (n=3), 2025 (n=9) — drawn dashed, excluded from every figure here.

## Listing grid/list
Header: "Listings, N matching the filters above". Controls: List/Grid view
toggle, Sort dropdown ("Newest listings first"), Per-page dropdown (50).

Grid card:
- Photo
- Top-left: flag + source-colour dot + registration date (YYYY/MM)
- Top-right: **"NEW"** badge (orange) when new since last scrape
- Ad title (raw), subtitle line (variant · colour · power kW, whatever the
  source has)
- **"not yet tracked"** when the listing has only one snapshot so far (no
  price history yet — first time seen)
- Price, mileage
- Occasionally a battery **SoH %** (State of Health) when the source
  provides it (seen on a Kleinanzeigen card)

## New fields this adds to the Phase 1 data model
Not in the original schema, needed for Phase 4 parity:
- `power_kw` (numeric) — **done**, added in Phase 2. AutoScout24's
  `vehicleDetails` has it directly; Tesla's has it in `EmissionsData.power`.
- `color` (categorical + "unknown" bucket) — **done for Tesla** (`PAINT`,
  e.g. `["BLACK"]`). AutoScout24's search-results payload doesn't include it
  despite the site having a colour filter — would need the individual
  listing page, not just search results, so still missing there.
- `battery_soh_percent` (optional, source-dependent) — confirmed real on
  both Kleinanzeigen (~2 of 27 listings in one sample, e.g. "91,8 SOH") and
  Használtautó.hu (multiple listings, e.g. "91% SOH", "SOH: 95.5%"), always
  as free text buried in the ad title or description, format inconsistent
  across sources and even within one — deliberately not extracted yet
  rather than guessing a regex off a handful of samples.
- `description_raw` (short free text, for the hover-card snippet) — real on
  Kleinanzeigen (in the search page's `ImageObject` JSON-LD blocks) and
  Tesla (not checked yet); not wired up yet, no RawListing field for it.
- watchlist membership as a **per-listing** flag/join table, not a saved
  filter preset (it behaves like "highlight this specific car", same as
  "new since last scrape")
- `excluded` as a first-class per-listing flag (drives both the depreciation
  chart's dashed/excluded treatment and the main filter bar's "show excluded
  listings" toggle) — **partially resolved in Phase 3**: `depreciation.py`'s
  `DepreciationBucket.is_thin` (n below `min_bucket_size`) covers the
  thin-bucket half of this. An outlier/implausible-price heuristic for
  individual listings is still open — not needed until Phase 4 actually
  renders the "show excluded listings" toggle.

## Resolved in Phase 3 (`src/car_tracker/analysis/`)
- Trend-line algorithm: binned median (`trend.py`), not LOESS — a
  reasonable default, not a settled choice; see README's Phase 3 section
  for the reasoning and what to reach for if it doesn't look smooth enough
  once real data is flowing.
- Thin-bucket rule: `n < min_bucket_size` (default 10).

## Resolved in Phase 4 (`frontend/`)
Built to spec, with a few deliberate simplifications rather than settled
"no":
- **"held €X for N days"** hover-card feature — implemented as specified;
  reads `0`/same-day as "held at this price since today" rather than
  "0 days", which reads more naturally.
- **"not yet tracked" grid badge** — not added as a separate badge; a
  first-seen listing already shows "NEW" and its hover card already
  degrades to "held ... since today", so a second badge saying the same
  thing seemed redundant. Revisit if that turns out to read as confusing
  rather than redundant once this runs against real day-over-day scrapes.
- **Description snippet in hover card** — not added; `description_raw` was
  never wired into `RawListing` for any source (see field list above), so
  there's nothing to show yet.
- **FX rate in the chart caption** — not added; the caption states the
  color encoding and interaction hint but not the day's HUF/€ rate. Minor,
  easy to add once `fx/ecb.py`'s rate is threaded through the export.
- **"Versus buying new" insight card** and the **shaded confidence band**
  on the depreciation chart — not implemented, matching the Phase 3 gap
  already documented in the README (no new-car price reference point from
  any of the four used-listing sources).
- **Trend line**: binned-median (Phase 3's choice), not the curved
  LOESS-style line in the reference screenshots — already flagged as a
  reasonable-default, not a settled choice; see README's Phase 3 section.

## Open questions for Phase 5+
- Where `power_kw` / `color` / `battery_soh_percent` actually come from per
  source (some sites won't have all of these) — see the field list above.
- Per-listing outlier/implausible-price exclusion rule (the other half of
  `excluded`; the depreciation module currently only excludes at the
  bucket level via `is_thin`, not per individual listing).
