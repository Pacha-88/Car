import { CHASSIS_LABELS, SOURCE_COLOR_VAR, SOURCE_LABELS, VARIANT_LABELS, type Listing } from "../types";
import { Chip, type ChipState } from "./Chip";
import { RangeSlider } from "./RangeSlider";
import {
  NAMED_COUNTRIES,
  REST_OF_EU,
  clearFacet,
  dataBounds,
  isFacetNarrowed,
  toggleFacet,
  type FacetMode,
  type FilterState,
} from "../lib/filters";
import { useMoney } from "../lib/moneyContext";

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
  green: "#3d6b45",
  brown: "#6b4a32",
  beige: "#cfc3a5",
  yellow: "#d6c02f",
  orange: "#cc7a2b",
  gold: "#b9962f",
  bronze: "#9a6c3c",
  purple: "#6f4a8f",
};

const MODEL_CHASSIS_OPTIONS: Record<string, string[]> = {
  model_y: ["legacy", "juniper", "unknown"],
  model_3: ["legacy", "highland", "unknown"],
};

interface FilterBarProps {
  filters: FilterState;
  onChange: (next: FilterState) => void;
  modelListings: Listing[]; // all listings for the active model, unfiltered - for bounds/option discovery
  newCount: number;
  watchlistCount: number;
  dealCount: number;
  onReset: () => void;
}

export function FilterBar({ filters, onChange, modelListings, newCount, watchlistCount, dealCount, onReset }: FilterBarProps) {
  const money = useMoney();
  const bounds = dataBounds(modelListings);
  const sourcesPresent = [...new Set(modelListings.map((l) => l.source))];
  // Commonest first, Unknown last: the row is data-driven, so insertion
  // order would otherwise be whatever the export happened to list first.
  const colorsPresent = (() => {
    const counts = new Map<string, number>();
    for (const l of modelListings) {
      const key = l.color ?? "unknown";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => (a[0] === "unknown" ? 1 : b[0] === "unknown" ? -1 : b[1] - a[1]))
      .map(([key]) => key);
  })();
  const chassisOptions = MODEL_CHASSIS_OPTIONS[filters.model] ?? ["legacy", "unknown"];

  const countryOptions = [...NAMED_COUNTRIES, REST_OF_EU];
  const variantOptions = ["long_range_awd", "long_range_rwd", "performance", "rwd", "other"];
  const sellerOptions = ["dealer", "private"];

  function set<K extends keyof FilterState>(key: K, value: FilterState[K]) {
    onChange({ ...filters, [key]: value });
  }

  // Every handle, not just the two that move first. Checking only the low
  // ends meant dragging the price or mileage MAX down hid listings while
  // the bar still said "showing everything" and Reset all stayed disabled -
  // a filter you could apply but not undo. `!==` rather than a narrowing
  // comparison on purpose: a handle parked off its default is something to
  // reset even when it happens to hide nothing.
  const rangesTouched = [
    filters.yearRange[0] !== bounds.yearRange[0] || filters.yearRange[1] !== bounds.yearRange[1],
    filters.priceRange[0] !== bounds.priceRange[0] || filters.priceRange[1] !== bounds.priceRange[1],
    filters.mileageRange[0] !== bounds.mileageRange[0] || filters.mileageRange[1] !== bounds.mileageRange[1],
  ].filter(Boolean).length;

  const narrowedGroups =
    Number(isFacetNarrowed(filters.countries, countryOptions, "all-selected")) +
    Number(isFacetNarrowed(filters.sources, sourcesPresent, "all-selected")) +
    Number(isFacetNarrowed(filters.sellerTypes, sellerOptions, "all-selected")) +
    Number(isFacetNarrowed(filters.variants, variantOptions, "all-selected")) +
    Number(isFacetNarrowed(filters.chassisGens, chassisOptions, "all-selected")) +
    Number(isFacetNarrowed(filters.colors, colorsPresent, "opt-in")) +
    rangesTouched +
    Number(filters.watchlistOnly) +
    Number(filters.dealsOnly) +
    Number(filters.newOnly);

  return (
    <section className="rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-1)]">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="flex items-baseline gap-2">
          <span className="eyebrow">Filters</span>
          <span className="text-xs text-muted">
            {narrowedGroups === 0
              ? "showing everything — click a chip to narrow to it"
              : `${narrowedGroups} active`}
          </span>
        </div>
        <button
          type="button"
          onClick={onReset}
          disabled={narrowedGroups === 0}
          className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-secondary transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-primary disabled:cursor-default disabled:opacity-35 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-secondary"
        >
          Reset all
        </button>
      </header>

      <div className="flex flex-col gap-4 px-4 py-3.5">
        {/* Where the car is and who is selling it */}
        <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
          <FacetGroup
            label="Country"
            options={countryOptions}
            selected={filters.countries}
            mode="all-selected"
            onChange={(v) => set("countries", v)}
            renderLabel={(c) => `${COUNTRY_FLAGS[c]} ${COUNTRY_LABELS[c]}`}
          />
          <FacetGroup
            label="Marketplace"
            options={sourcesPresent}
            selected={filters.sources}
            mode="all-selected"
            onChange={(v) => set("sources", v)}
            renderLabel={(s) => SOURCE_LABELS[s] ?? s}
            renderDot={(s) => SOURCE_COLOR_VAR[s]}
          />
          <FacetGroup
            label="Seller"
            options={sellerOptions}
            selected={filters.sellerTypes}
            mode="all-selected"
            onChange={(v) => set("sellerTypes", v)}
            renderLabel={(s) => (s === "dealer" ? "Dealer" : "Private")}
          />
        </div>

        {/* What the car is */}
        <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
          <FacetGroup
            label="Variant"
            options={variantOptions}
            selected={filters.variants}
            mode="all-selected"
            onChange={(v) => set("variants", v)}
            renderLabel={(v) => VARIANT_LABELS[v]}
          />
          <FacetGroup
            label="Chassis"
            options={chassisOptions}
            selected={filters.chassisGens}
            mode="all-selected"
            onChange={(v) => set("chassisGens", v)}
            renderLabel={(c) => (c === "unknown" ? "Unknown" : CHASSIS_LABELS[c])}
          />
          <FacetGroup
            label="Colour"
            options={colorsPresent}
            selected={filters.colors}
            mode="opt-in"
            onChange={(v) => set("colors", v)}
            renderLabel={(c) => (c === "unknown" ? "Unknown" : c[0].toUpperCase() + c.slice(1))}
            renderSwatch={(c) => (c === "unknown" ? "transparent" : (COLOR_SWATCHES[c] ?? "#7a7a7a"))}
          />
        </div>

        {/* Ranges */}
        <div className="flex flex-wrap items-end gap-x-8 gap-y-4 border-t border-border pt-3.5">
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
            formatValue={money.formatTick}
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
        </div>

        {/* Shortcuts and chart options */}
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-border pt-3.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="eyebrow mr-1">Shortcuts</span>
            <Chip
              label="New since last scrape"
              count={newCount}
              dot="var(--status-warning)"
              state={filters.newOnly ? "on" : "calm"}
              onClick={() => set("newOnly", !filters.newOnly)}
            />
            <Chip
              label="Watchlist"
              count={watchlistCount}
              dot="var(--series-1)"
              state={filters.watchlistOnly ? "on" : "calm"}
              onClick={() => set("watchlistOnly", !filters.watchlistOnly)}
            />
            <Chip
              label="Deals"
              count={dealCount}
              dot="var(--status-good)"
              state={filters.dealsOnly ? "on" : "calm"}
              onClick={() => set("dealsOnly", !filters.dealsOnly)}
            />
          </div>

          <div className="ml-auto flex items-center gap-5">
            <ToggleSwitch label="Trend line" checked={filters.showTrendLine} onChange={(v) => set("showTrendLine", v)} />
            <ToggleSwitch
              label="Show excluded listings"
              checked={filters.showExcluded}
              onChange={(v) => set("showExcluded", v)}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * A row of chips over one facet. It owns the click model so every group in
 * the bar behaves the same way regardless of how its set is stored, and it
 * shows in its own header whether it is narrowing anything - which is the
 * only way to tell, now that an unnarrowed group is deliberately quiet.
 */
function FacetGroup({
  label,
  options,
  selected,
  mode,
  onChange,
  renderLabel,
  renderDot,
  renderSwatch,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  mode: FacetMode;
  onChange: (next: Set<string>) => void;
  renderLabel: (value: string) => string;
  renderDot?: (value: string) => string;
  renderSwatch?: (value: string) => string;
}) {
  const narrowed = isFacetNarrowed(selected, options, mode);
  const shownCount = options.filter((o) => selected.has(o)).length;

  return (
    <div className="min-w-0" data-facet={label.toLowerCase()}>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="eyebrow">{label}</span>
        {narrowed ? (
          <button
            type="button"
            onClick={() => onChange(clearFacet(options, mode))}
            // The count reads as the button's name otherwise ("1/4"), which
            // says nothing about what pressing it does.
            aria-label={`Clear the ${label.toLowerCase()} filter`}
            title={`Clear the ${label.toLowerCase()} filter`}
            className="inline-flex items-center gap-1 rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-accent-ink transition-opacity hover:opacity-80"
          >
            <span className="numeral">
              {shownCount}/{options.length}
            </span>
            <span aria-hidden>×</span>
          </button>
        ) : (
          // Same box as the narrowed badge, so a group's header does not
          // jump when you narrow it.
          <span className="rounded-full border border-border px-1.5 py-px text-[10px] font-medium text-muted">all</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const state: ChipState = !narrowed ? "calm" : selected.has(o) ? "on" : "off";
          return (
            <Chip
              key={o}
              label={renderLabel(o)}
              state={state}
              dot={renderDot?.(o)}
              swatch={renderSwatch?.(o)}
              title={narrowed ? undefined : `Show only ${renderLabel(o)}`}
              onClick={() => onChange(toggleFacet(selected, o, options, mode))}
            />
          );
        })}
      </div>
    </div>
  );
}

function ToggleSwitch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex cursor-pointer items-center gap-2 text-xs text-secondary transition-colors hover:text-primary"
    >
      <span
        className={`relative inline-block h-4 w-7 shrink-0 rounded-full border transition-colors ${
          checked ? "border-accent bg-accent" : "border-border bg-baseline"
        }`}
      >
        {/* left-0 is load-bearing: a <button> is text-align:center by default,
            and an absolutely positioned child with `left:auto` takes its
            static position from that - which parked the knob outside the
            track. */}
        <span
          className={`absolute left-0 top-[3px] h-2.5 w-2.5 rounded-full transition-transform ${
            checked ? "translate-x-[15px] bg-accent-ink" : "translate-x-[3px] bg-secondary"
          }`}
        />
      </span>
      {label}
    </button>
  );
}
