import { CHASSIS_LABELS, SOURCE_COLOR_VAR, SOURCE_LABELS, VARIANT_LABELS, type Listing } from "../types";
import { Chip } from "./Chip";
import { RangeSlider } from "./RangeSlider";
import { NAMED_COUNTRIES, REST_OF_EU, type FilterState, dataBounds } from "../lib/filters";

const COUNTRY_FLAGS: Record<string, string> = { DE: "🇩🇪", AT: "🇦🇹", HU: "🇭🇺", [REST_OF_EU]: "🇪🇺" };
const COUNTRY_LABELS: Record<string, string> = { DE: "Germany", AT: "Austria", HU: "Hungary", [REST_OF_EU]: "Rest of EU" };

const COLOR_SWATCHES: Record<string, string> = {
  white: "#f5f5f0",
  black: "#1a1a1a",
  grey: "#8a8a86",
  gray: "#8a8a86",
  silver: "#c8c8c4",
  blue: "#3a5f8a",
  red: "#a83232",
};

const MODEL_CHASSIS_OPTIONS: Record<string, string[]> = {
  model_y: ["legacy", "juniper", "unknown"],
  model_3: ["legacy", "highland", "unknown"],
};

function toggleInSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

interface FilterBarProps {
  filters: FilterState;
  onChange: (next: FilterState) => void;
  modelListings: Listing[]; // all listings for the active model, unfiltered - for bounds/option discovery
  newCount: number;
  watchlistCount: number;
  onReset: () => void;
}

export function FilterBar({ filters, onChange, modelListings, newCount, watchlistCount, onReset }: FilterBarProps) {
  const bounds = dataBounds(modelListings);
  const sourcesPresent = [...new Set(modelListings.map((l) => l.source))];
  const colorsPresent = [...new Set(modelListings.map((l) => l.color ?? "unknown"))];
  const chassisOptions = MODEL_CHASSIS_OPTIONS[filters.model] ?? ["legacy", "unknown"];

  function set<K extends keyof FilterState>(key: K, value: FilterState[K]) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-3">
      {/* Row 1: country / marketplace / seller */}
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
        <FilterGroup label="Country">
          {[...NAMED_COUNTRIES, REST_OF_EU].map((c) => (
            <Chip
              key={c}
              label={`${COUNTRY_FLAGS[c]} ${COUNTRY_LABELS[c]}`}
              active={filters.countries.has(c)}
              onClick={() => set("countries", toggleInSet(filters.countries, c))}
            />
          ))}
        </FilterGroup>

        <FilterGroup label="Marketplace">
          {sourcesPresent.map((s) => (
            <Chip
              key={s}
              label={SOURCE_LABELS[s] ?? s}
              dot={SOURCE_COLOR_VAR[s]}
              active={filters.sources.has(s)}
              onClick={() => set("sources", toggleInSet(filters.sources, s))}
            />
          ))}
        </FilterGroup>

        <FilterGroup label="Seller">
          {(["dealer", "private"] as const).map((s) => (
            <Chip
              key={s}
              label={s === "dealer" ? "Dealer" : "Private"}
              active={filters.sellerTypes.has(s)}
              onClick={() => set("sellerTypes", toggleInSet(filters.sellerTypes, s))}
            />
          ))}
        </FilterGroup>
      </div>

      {/* Row 2: variant / chassis / colour */}
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
        <FilterGroup label="Variant">
          {(["long_range_awd", "performance", "rwd", "other"] as const).map((v) => (
            <Chip
              key={v}
              label={VARIANT_LABELS[v]}
              active={filters.variants.has(v)}
              onClick={() => set("variants", toggleInSet(filters.variants, v))}
            />
          ))}
        </FilterGroup>

        <FilterGroup label="Chassis">
          {chassisOptions.map((c) => (
            <Chip
              key={c}
              label={c === "unknown" ? "Unknown" : CHASSIS_LABELS[c]}
              active={filters.chassisGens.has(c)}
              onClick={() => set("chassisGens", toggleInSet(filters.chassisGens, c))}
            />
          ))}
        </FilterGroup>

        <FilterGroup label="Colour" hint="no filter = all">
          {colorsPresent.map((c) => (
            <Chip
              key={c}
              label={c === "unknown" ? "Unknown" : c[0].toUpperCase() + c.slice(1)}
              swatch={c === "unknown" ? "transparent" : (COLOR_SWATCHES[c] ?? "#7a7a7a")}
              active={filters.colors.has(c)}
              onClick={() => set("colors", toggleInSet(filters.colors, c))}
            />
          ))}
        </FilterGroup>
      </div>

      {/* Row 3: sliders / highlights / toggles */}
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3 border-t border-border pt-3">
        <RangeSlider
          label="Year"
          min={bounds.yearRange[0]}
          max={bounds.yearRange[1]}
          value={filters.yearRange}
          onChange={(v) => set("yearRange", v)}
          formatValue={(v) => String(v)}
        />
        <RangeSlider
          label="Price"
          min={0}
          max={Math.ceil(bounds.priceRange[1] / 1000) * 1000}
          step={500}
          value={filters.priceRange}
          onChange={(v) => set("priceRange", v)}
          formatValue={(v) => `€${Math.round(v / 1000)}k`}
        />
        <RangeSlider
          label="Mileage"
          min={0}
          max={Math.ceil(bounds.mileageRange[1] / 5000) * 5000}
          step={1000}
          value={filters.mileageRange}
          onChange={(v) => set("mileageRange", v)}
          formatValue={(v) => `${Math.round(v / 1000)}k`}
        />

        <FilterGroup label="Highlight">
          <Chip
            label="New since last scrape"
            count={newCount}
            dot="var(--status-warning)"
            active={filters.highlightNew}
            onClick={() => set("highlightNew", !filters.highlightNew)}
          />
          <Chip
            label="Watchlist"
            count={watchlistCount}
            dot="var(--series-1)"
            active={filters.watchlistOnly}
            onClick={() => set("watchlistOnly", !filters.watchlistOnly)}
          />
        </FilterGroup>

        <div className="flex items-center gap-4">
          <ToggleSwitch label="Trend line" checked={filters.showTrendLine} onChange={(v) => set("showTrendLine", v)} />
          <ToggleSwitch
            label="Show excluded listings"
            checked={filters.showExcluded}
            onChange={(v) => set("showExcluded", v)}
          />
        </div>

        <button
          type="button"
          onClick={onReset}
          className="ml-auto rounded-md border border-border px-3 py-1.5 text-xs font-medium text-secondary hover:text-primary hover:bg-surface-2"
        >
          Reset filters
        </button>
      </div>
    </div>
  );
}

function FilterGroup({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-baseline gap-1.5 text-[10px] uppercase tracking-wide text-muted">
        <span>{label}</span>
        {hint && <span className="normal-case opacity-70">({hint})</span>}
      </div>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function ToggleSwitch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-xs text-secondary">
      <span
        className={`relative inline-block h-4 w-7 rounded-full transition-colors ${checked ? "bg-series-1" : "bg-baseline"}`}
        onClick={() => onChange(!checked)}
      >
        <span
          className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform ${
            checked ? "translate-x-3.5" : "translate-x-0.5"
          }`}
        />
      </span>
      {label}
    </label>
  );
}
