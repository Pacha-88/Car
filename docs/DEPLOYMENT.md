# Going live (Phase 5)

Everything code-side is done and tested (see below). Three one-time steps are
left, and all three need your own accounts — nothing here can be automated
from inside this repo.

## 1. Create a Supabase Postgres project

1. Go to [supabase.com](https://supabase.com) and sign in (GitHub login is
   easiest since you're already there).
2. **New project** → pick a name (e.g. `car-tracker`), let it generate a
   database password, pick a region close to Europe (e.g. Frankfurt).
   Wait ~2 minutes for it to provision.
3. **Project Settings → Database → Connect** → copy the **Transaction
   pooler** connection string (not the direct connection — the pooler is
   built for exactly this project's usage pattern: a short-lived connection
   once a day from GitHub Actions, not a long-lived server).
4. It looks like `postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-...pooler.supabase.com:6543/postgres`.
   Fill in your real password, and change the scheme from `postgresql://` to
   `postgresql+psycopg://` (SQLAlchemy needs the driver name in the URL).
   Final shape:
   `postgresql+psycopg://postgres.xxxxx:your-real-password@aws-...pooler.supabase.com:6543/postgres`

You don't need to create any tables yourself — the workflow runs
`car-tracker init-db` every time, which creates them on first run and is a
no-op afterwards.

## 2. Add it as a GitHub Actions secret

Repo → **Settings → Secrets and variables → Actions → New repository
secret**:
- Name: `DATABASE_URL`
- Value: the connection string from step 1

This is the only credential the pipeline needs. It's never written to a file
or logged — `.github/workflows/scrape-and-deploy.yml` reads it straight into
an environment variable.

## 3. Enable GitHub Pages

Repo → **Settings → Pages → Build and deployment → Source** → select
**"GitHub Actions"** (not "Deploy from a branch"). Nothing else to pick — the
workflow's `deploy-pages` step handles the rest.

## A note on branches

GitHub only evaluates a `schedule:` trigger from workflow files on the
repo's **default branch** — a schedule defined on any other branch never
fires, no matter how long you wait. Right now `claude/auto-portal-planning-szpk2m`
*is* this repo's only branch, so it's already the default branch and no
merge step is needed — steps 1-3 above are all that's left. This only
becomes relevant if you later create a `main` and move work there: at that
point, bring this workflow file along, since the schedule follows whichever
branch is set as default in **Settings → General → Default branch**.

## Running it

- **Manually, any time**: Actions tab → "Scrape and deploy dashboard" →
  **Run workflow**. Good for the first run, or a backfill.
- **Automatically**: every day at 05:00 UTC (~06:00–07:00 CET/CEST,
  before the day starts) once step 4 is done.

First run takes a few minutes (scrape all four sources, build the frontend,
deploy). After that it's live at `https://<your-github-username>.github.io/<repo-name>/`
(lowercase). Check the Actions tab for progress and logs.

## What to expect from the first few runs

- **Tesla and Használtautó.hu may fail while AutoScout24 and Kleinanzeigen
  succeed** — both block some networks at the site level (Akamai /
  Cloudflare bot defenses; see README). The workflow is built to tolerate
  this: a partial failure still exports and deploys whatever the other
  sources found, and only shows a (non-blocking) warning annotation on the
  run rather than turning it red. GitHub Actions' own IP ranges are
  well-known to sites' bot-detection systems, so don't be surprised if this
  persists — it's the same class of block already documented from this
  project's dev sandbox, not a new bug.
- **The very first run will mark every listing "NEW"** — "new since last
  scrape" is relative to the previous scrape, and there isn't one yet. This
  corrects itself from the second run onward.
- **"Held €X for N days" only becomes meaningful after a few days** of
  accumulated snapshots, for the same reason.
- Supabase's free tier pauses a project after a week with zero connections —
  a daily scrape keeps it active on its own, nothing to do here.

## Fixed after the first live run

The first real GitHub Actions run failed, and surfaced two bugs that local
testing had missed. Both are fixed; recorded here because the second one is
easy to reintroduce.

- **`DuplicatePreparedStatement: prepared statement "_pg3_0" already
  exists`** — killed 24 of 32 scrape combos. Supabase's pooler on port 6543
  is PgBouncer in *transaction* mode: it hands each transaction whatever
  server connection happens to be free, so psycopg3's automatic server-side
  `PREPARE` re-prepares the same statement name on a connection that
  already has it. Fixed in `db/session.py` by disabling prepared statements
  (`prepare_threshold=None`) for every psycopg URL. **This is why the
  original local Postgres test passed and production still broke** — that
  test used a *direct* connection, with no pooler in the path. Re-verified
  against a real local PgBouncer in transaction mode: reproduced the exact
  failure first, then ran 8 consecutive scrapes and a full `scrape-all`
  clean.
- **`FileNotFoundError: frontend/public/data/listings.json`** — the export
  target directory doesn't exist in a fresh clone, since the file it holds
  is gitignored generated data and git doesn't track empty directories.
  `export` now creates the path.

## What was verified before this was written

- The full pipeline (`init-db` → `scrape` → `export`) run end-to-end against
  a real local PostgreSQL 16 instance (not just SQLite): schema translates
  cleanly (native `json`, `timestamp without time zone` matching this
  project's naive-UTC convention, foreign keys, indexes all correct), and a
  second scrape run against the same DB correctly appended new snapshots to
  the same listings rather than duplicating them — the core mechanic the
  price-history feature depends on.
- `scrape-all` run for real against every source/model/country combo this
  project tracks: AutoScout24 (all 8 countries) and Kleinanzeigen both
  succeeded; Tesla and Használtautó.hu both hit real 403s from this
  sandbox's network — which is what motivated the workflow's
  partial-failure tolerance above, rather than guessing it might be needed.
- The ECB fx-rate feed (`fx/ecb.py`), live for the first time this phase:
  29 currencies including HUF, correct rate_date.
- The production frontend build (not just dev mode), served from a
  simulated `/<repo>/` subpath the way GitHub Pages actually serves project
  sites: renders correctly, no path-resolution errors.
- Every GitHub Action version referenced in the workflow was checked
  against its current release (not assumed from training data) — several
  had moved multiple major versions ahead, and `astral-sh/setup-uv` in
  particular now requires a full pinned version tag rather than a floating
  major-version tag.
