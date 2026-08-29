import { useEffect, useMemo, useState } from "react";
import { DepreciationModule } from "./components/DepreciationModule";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { FilterBar } from "./components/FilterBar";
import { ListingGrid } from "./components/ListingGrid";
import { MarketTrendChart } from "./components/MarketTrendChart";
import { PriceScatterChart } from "./components/PriceScatterChart";
import { StatTiles } from "./components/StatTiles";
import { MoneyProvider } from "./hooks/useMoney";
import { useMoney } from "./lib/moneyContext";
import { useListings } from "./hooks/useListings";
import { useWatchlist } from "./hooks/useWatchlist";
import { computeDealScores } from "./lib/dealScore";
import { isPriceDrop, priceChange } from "./lib/priceHistory";
import { ageBucketIndex, ageInYears, computeDepreciationCurve } from "./lib/depreciation";
import { applyFilters, defaultFilterState, type FilterState } from "./lib/filters";
import { linearSlope } from "./lib/trend";
import type { Listing, Model } from "./types";

const DEAL_TIERS_KEPT = new Set(["great", "good"]);

const MIN_BUCKET_SIZE = 10;
const REFERENCE_KM_FOR_EXCLUSION = 60_000;

/** How old the data is, said out loud. A dot that is always green claims
 * the export is fresh whatever its date; this one goes amber after a
 * missed day and red after a missed week, which is the actual question
 * ("is this still the market?"). */
// Read once at module load: the age only needs day granularity, and a
// clock call inside render is both impure and pointless here.
const LOADED_AT = Date.now();

function ScrapeFreshness({ date }: { date: string }) {
  const days = Math.floor((LOADED_AT - new Date(`${date}T12:00:00`).getTime()) / 86_400_000);
  const tone = days <= 1 ? "bg-status-good" : days <= 7 ? "bg-status-warning" : "bg-status-critical";
  const age = days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
  return (
    <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted" title={`Scraped ${age}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${tone}`} aria-hidden />
      Last scraped {date}
      {days > 1 && <span>· {age}</span>}
    </p>
  );
}

/** The one segmented-control look, shared by the model tabs and the
 * display toggles - a single raised strip, the selected cell inverted. */
function Segmented({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-1 p-0.5 shadow-[var(--shadow-1)]">
      {children}
    </div>
  );
}

function SegmentedButton({
  active,
  onClick,
  children,
  title,
}: {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`rounded-[6px] px-2.5 py-1 text-xs font-medium transition-colors ${
        active ? "bg-accent text-accent-ink" : "text-secondary hover:bg-surface-2 hover:text-primary"
      }`}
    >
      {children}
    </button>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    return (localStorage.getItem("car-tracker.theme") as "dark" | "light" | null) ?? "dark";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("car-tracker.theme", theme);
  }, [theme]);
  return (
    <SegmentedButton
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {theme === "dark" ? "☀︎" : "☾"}
    </SegmentedButton>
  );
}

function CurrencyToggle() {
  const { currency, setCurrency, hufPerEur } = useMoney();
  // Without a stored rate there is nothing to switch to, and a dead
  // button that silently does nothing is worse than no button.
  if (hufPerEur === null) return null;
  return (
    <SegmentedButton
      onClick={() => setCurrency(currency === "HUF" ? "EUR" : "HUF")}
      title={`Showing ${currency} · 1 € = ${Math.round(hufPerEur)} Ft at the last scrape`}
    >
      {currency === "HUF" ? "Ft" : "€"}
    </SegmentedButton>
  );
}

export default function App() {
  // useListings fetches, so it is called once here and its result handed
  // down - the provider needs the rate out of that same payload, and
  // calling the hook twice would mean fetching the export twice.
  const data = useListings();
  return (
    <MoneyProvider hufPerEur={data.hufPerEur}>
      <Dashboard data={data} />
    </MoneyProvider>
  );
}

function Dashboard({ data }: { data: ReturnType<typeof useListings> }) {
  const { listings, latestScrapeDate, marketHistory, loading, error } = data;
  const { watchlist, toggle: toggleWatchlist } = useWatchlist();
  const [model, setModel] = useState<Model>("model_y");
  const [filters, setFilters] = useState<FilterState | null>(null);

  const modelListings = useMemo(() => listings.filter((l) => l.model === model), [listings, model]);

  // Deal scores are fit over the whole model's listings, not the filtered
  // subset, so a car's "% vs market" stays put as you move the filters.
  const dealScores = useMemo(() => computeDealScores(modelListings), [modelListings]);

  // (Re)seed filter bounds whenever the model switches or data first loads.
  // Adjusted during render (React's derived-state pattern), not in an
  // effect: the effect version painted a full frame with the stale filters
  // and then re-rendered everything - at live scale (3.200+ listings) that
  // doubled the cost of every model switch.
  const [seededFor, setSeededFor] = useState<{ listings: Listing[]; model: Model } | null>(null);
  if (listings.length > 0 && (seededFor?.listings !== listings || seededFor.model !== model)) {
    setSeededFor({ listings, model });
    setFilters(defaultFilterState(listings, model));
  }

  const preExclusion = useMemo(() => {
    if (!filters) return [];
    return applyFilters(modelListings, filters, watchlist);
  }, [modelListings, filters, watchlist]);

  // Which age buckets are too thin to say anything about is a property of
  // the MARKET, not of your current filter - so it is measured over the
  // whole model's listings, exactly as the deal scores above are.
  //
  // Measuring it on the filtered subset made every narrow filter empty the
  // grid: pick a colour with 15 cars and each age bucket holds fewer than
  // the ten a bucket needs, so all of them count as thin and every car is
  // hidden. Live numbers on real data: Blue 15 cars -> 0 shown, Silver 5 ->
  // 0, Red 5 -> 0, while White (83) lost only 8. It reads as "the colour
  // filter is broken", and it was doing this to every filter.
  const thinBucketIndices = useMemo(() => {
    const input = modelListings
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
  }, [modelListings]);

  const displayed = useMemo(() => {
    if (!filters || filters.showExcluded) return preExclusion;
    const asOf = new Date();
    return preExclusion.filter((l) => {
      if (!l.firstRegistration) return true; // can't classify -> don't hide
      const bucketIndex = ageBucketIndex(ageInYears(new Date(l.firstRegistration), asOf));
      return !thinBucketIndices.has(bucketIndex);
    });
  }, [preExclusion, filters, thinBucketIndices]);

  // The two shortcut filters narrow the buyer-facing views (grid + scatter)
  // together; the depreciation module stays on the full set. "New" used to
  // narrow the chart alone, which left the grid and the stat tiles claiming
  // 386 listings beside an empty plot.
  const gridListings = useMemo(() => {
    let out = displayed;
    if (filters?.dealsOnly) {
      out = out.filter((l) => DEAL_TIERS_KEPT.has(dealScores.get(l.id)?.tier ?? ""));
    }
    if (filters?.newOnly) out = out.filter((l) => l.isNew);
    if (filters?.priceDropsOnly) out = out.filter((l) => isPriceDrop(priceChange(l)));
    return out;
  }, [displayed, filters, dealScores]);

  const dealCount = useMemo(
    () => displayed.filter((l) => DEAL_TIERS_KEPT.has(dealScores.get(l.id)?.tier ?? "")).length,
    [displayed, dealScores],
  );

  // Counted over this model's listings rather than the whole watchlist: the
  // chip used to advertise cars starred on the OTHER model, so clicking it
  // showed nothing.
  const watchlistCount = useMemo(
    () => modelListings.filter((l) => watchlist.has(l.id)).length,
    [modelListings, watchlist],
  );

  // The registration-year palette is anchored to the model, not to whatever
  // survives the filters. Anchoring it to the visible points repainted the
  // survivors on every filter click - isolate one chassis and 2022 went
  // from purple to red - which is exactly what a categorical colour must
  // never do.
  const paletteMaxYear = useMemo(() => {
    let max = 0;
    for (const l of modelListings) {
      const y = l.firstRegistration ? Number(l.firstRegistration.slice(0, 4)) : (l.modelYear ?? 0);
      if (y > max) max = y;
    }
    return max || new Date().getFullYear();
  }, [modelListings]);

  // Measured over exactly what the grid and the chart are showing, the two
  // shortcut chips included. Reading them off `displayed` instead left the
  // header saying 386 listings above a grid showing 51.
  const eurPer10kKm = useMemo(() => {
    const points = gridListings
      .filter((l) => l.mileageKm !== null)
      .map((l) => [l.mileageKm as number, l.priceEur] as [number, number]);
    if (points.length < 2) return null;
    try {
      return linearSlope(points).slope * 10_000;
    } catch {
      return null;
    }
  }, [gridListings]);

  const newCount = useMemo(() => displayed.filter((l) => l.isNew).length, [displayed]);
  const dropCount = useMemo(() => displayed.filter((l) => isPriceDrop(priceChange(l))).length, [displayed]);
  // Counted over the same set the grid draws from, so the chip promises
  // the number of cars clicking it actually leaves - `modelListings`
  // ignores the other facets and advertised five where four survived.
  const fsdCount = useMemo(() => displayed.filter((l) => l.hasFsd).length, [displayed]);

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
    <div className="mx-auto max-w-[1400px] px-5 py-5">
      <header className="mb-5 flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <div className="eyebrow">Used market · Germany · Austria · Hungary</div>
            <h1 className="mt-1.5 text-[22px] font-semibold leading-none tracking-tight text-primary">
              Tesla {model === "model_y" ? "Model Y" : "Model 3"}
            </h1>
            {latestScrapeDate && <ScrapeFreshness date={latestScrapeDate} />}
          </div>
          <div className="flex items-center gap-2">
            <Segmented>
              {(["model_y", "model_3"] as const).map((m) => (
                <SegmentedButton key={m} active={model === m} onClick={() => setModel(m)}>
                  {m === "model_y" ? "Model Y" : "Model 3"}
                </SegmentedButton>
              ))}
            </Segmented>
            <Segmented>
              <CurrencyToggle />
              <ThemeToggle />
            </Segmented>
          </div>
        </div>

        <StatTiles listings={gridListings} eurPer10kKm={eurPer10kKm} />
      </header>

      <div className="mb-5">
        <FilterBar
          filters={filters}
          onChange={setFilters}
          modelListings={modelListings}
          newCount={newCount}
          watchlistCount={watchlistCount}
          dealCount={dealCount}
          dropCount={dropCount}
          fsdCount={fsdCount}
          onReset={() => setFilters(defaultFilterState(listings, model))}
        />
      </div>

      <div className="mb-5">
        <ErrorBoundary label="The price chart">
          <PriceScatterChart
            listings={gridListings}
            paletteMaxYear={paletteMaxYear}
            showTrendLine={filters.showTrendLine}
            watchlist={watchlist}
            onToggleWatchlist={toggleWatchlist}
            dealScores={dealScores}
          />
        </ErrorBoundary>
      </div>

      <div className="mb-5">
        <ErrorBoundary label="The market trend chart">
          <MarketTrendChart history={marketHistory} model={model} />
        </ErrorBoundary>
      </div>

      <div className="mb-5">
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
          latestScrapeDate={latestScrapeDate}
          saleTimes={data.saleTimes}
        />
      </ErrorBoundary>
    </div>
  );
}
