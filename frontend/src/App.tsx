import { useEffect, useMemo, useState } from "react";
import { DepreciationModule } from "./components/DepreciationModule";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { FilterBar } from "./components/FilterBar";
import { ListingGrid } from "./components/ListingGrid";
import { PriceScatterChart } from "./components/PriceScatterChart";
import { StatTiles } from "./components/StatTiles";
import { useListings } from "./hooks/useListings";
import { useWatchlist } from "./hooks/useWatchlist";
import { computeDealScores } from "./lib/dealScore";
import { ageBucketIndex, ageInYears, computeDepreciationCurve } from "./lib/depreciation";
import { applyFilters, defaultFilterState, type FilterState } from "./lib/filters";
import { linearSlope } from "./lib/trend";
import type { Model } from "./types";

const DEAL_TIERS_KEPT = new Set(["great", "good"]);

const MIN_BUCKET_SIZE = 10;
const REFERENCE_KM_FOR_EXCLUSION = 60_000;

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    return (localStorage.getItem("car-tracker.theme") as "dark" | "light" | null) ?? "dark";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("car-tracker.theme", theme);
  }, [theme]);
  return (
    <button
      type="button"
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      className="rounded-md border border-border px-2 py-1 text-xs text-secondary hover:text-primary"
    >
      {theme === "dark" ? "☀︎ Light" : "☾ Dark"}
    </button>
  );
}

export default function App() {
  const { listings, latestScrapeDate, loading, error } = useListings();
  const { watchlist, toggle: toggleWatchlist } = useWatchlist();
  const [model, setModel] = useState<Model>("model_y");
  const [filters, setFilters] = useState<FilterState | null>(null);

  const modelListings = useMemo(() => listings.filter((l) => l.model === model), [listings, model]);

  // Deal scores are fit over the whole model's listings, not the filtered
  // subset, so a car's "% vs market" stays put as you move the filters.
  const dealScores = useMemo(() => computeDealScores(modelListings), [modelListings]);

  // (Re)seed filter bounds whenever the model switches or data first loads.
  useEffect(() => {
    if (listings.length === 0) return;
    setFilters(defaultFilterState(listings, model));
  }, [listings, model]);

  const preExclusion = useMemo(() => {
    if (!filters) return [];
    return applyFilters(modelListings, filters, watchlist);
  }, [modelListings, filters, watchlist]);

  const thinBucketIndices = useMemo(() => {
    const input = preExclusion
      .filter((l) => l.firstRegistration && l.mileageKm !== null)
      .map((l) => ({
        firstRegistration: new Date(l.firstRegistration as string),
        mileageKm: l.mileageKm as number,
        priceEur: l.priceEur,
      }));
    if (input.length < 2) return new Set<number>();
    try {
      const buckets = computeDepreciationCurve(input, new Date(), {
        referenceKm: REFERENCE_KM_FOR_EXCLUSION,
        minBucketSize: MIN_BUCKET_SIZE,
      });
      return new Set(buckets.filter((b) => b.isThin).map((b) => b.bucketIndex));
    } catch {
      return new Set<number>();
    }
  }, [preExclusion]);

  const displayed = useMemo(() => {
    if (!filters || filters.showExcluded) return preExclusion;
    const asOf = new Date();
    return preExclusion.filter((l) => {
      if (!l.firstRegistration) return true; // can't classify -> don't hide
      const bucketIndex = ageBucketIndex(ageInYears(new Date(l.firstRegistration), asOf));
      return !thinBucketIndices.has(bucketIndex);
    });
  }, [preExclusion, filters, thinBucketIndices]);

  // "Deals only" narrows the buyer-facing views (grid + scatter) to cars
  // priced below market; the depreciation module stays on the full set.
  const gridListings = useMemo(() => {
    if (!filters?.dealsOnly) return displayed;
    return displayed.filter((l) => {
      const tier = dealScores.get(l.id)?.tier;
      return tier !== undefined && DEAL_TIERS_KEPT.has(tier);
    });
  }, [displayed, filters, dealScores]);

  const highlighted = useMemo(
    () => (filters?.highlightNew ? gridListings.filter((l) => l.isNew) : gridListings),
    [gridListings, filters],
  );

  const dealCount = useMemo(
    () => displayed.filter((l) => DEAL_TIERS_KEPT.has(dealScores.get(l.id)?.tier ?? "")).length,
    [displayed, dealScores],
  );

  const eurPer10kKm = useMemo(() => {
    const points = displayed
      .filter((l) => l.mileageKm !== null)
      .map((l) => [l.mileageKm as number, l.priceEur] as [number, number]);
    if (points.length < 2) return null;
    try {
      return linearSlope(points).slope * 10_000;
    } catch {
      return null;
    }
  }, [displayed]);

  const newCount = useMemo(() => preExclusion.filter((l) => l.isNew).length, [preExclusion]);

  if (loading) {
    return <div className="flex h-screen items-center justify-center text-sm text-muted">Loading listings…</div>;
  }
  if (error || !filters) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-2 text-sm text-muted">
        <p>{error ?? "No data yet."}</p>
        <p className="text-xs">
          Run <code className="rounded bg-surface-2 px-1.5 py-0.5">car-tracker export --out frontend/public/data/listings.json</code>{" "}
          from the project root, then reload.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-4">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-2 flex gap-1 rounded-lg bg-surface-1 p-1 text-sm">
            {(["model_y", "model_3"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setModel(m)}
                className={`rounded-md px-3 py-1 font-medium ${
                  model === m ? "bg-series-1 text-white" : "text-secondary hover:text-primary"
                }`}
              >
                {m === "model_y" ? "Model Y" : "Model 3"}
              </button>
            ))}
          </div>
          <div className="text-[10px] uppercase tracking-wide text-muted">Germany · Austria · Hungary — used market</div>
          <h1 className="text-lg font-semibold text-primary">
            Tesla {model === "model_y" ? "Model Y" : "Model 3"} — price vs mileage
          </h1>
          {latestScrapeDate && <p className="text-xs text-muted">Last scraped {latestScrapeDate}</p>}
        </div>
        <div className="flex items-center gap-3">
          <StatTiles listings={displayed} eurPer10kKm={eurPer10kKm} />
          <ThemeToggle />
        </div>
      </header>

      <div className="mb-4">
        <FilterBar
          filters={filters}
          onChange={setFilters}
          modelListings={modelListings}
          newCount={newCount}
          watchlistCount={watchlist.size}
          dealCount={dealCount}
          onReset={() => setFilters(defaultFilterState(listings, model))}
        />
      </div>

      <div className="mb-4">
        <ErrorBoundary label="The price chart">
          <PriceScatterChart
            listings={highlighted}
            showTrendLine={filters.showTrendLine}
            watchlist={watchlist}
            onToggleWatchlist={toggleWatchlist}
            dealScores={dealScores}
          />
        </ErrorBoundary>
      </div>

      <div className="mb-4">
        <ErrorBoundary label="The depreciation module">
          <DepreciationModule listings={displayed} />
        </ErrorBoundary>
      </div>

      <ErrorBoundary label="The listing grid">
        <ListingGrid
          listings={gridListings}
          watchlist={watchlist}
          onToggleWatchlist={toggleWatchlist}
          dealScores={dealScores}
        />
      </ErrorBoundary>
    </div>
  );
}
