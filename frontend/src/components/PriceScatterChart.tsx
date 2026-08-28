import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { binnedMedianTrend } from "../lib/trend";
import { yearColor, yearLegendEntries } from "../lib/colors";
import type { DealInfo } from "../lib/dealScore";
import { formatEur, formatKm, formatYearMonth } from "../lib/format";
import { CHASSIS_LABELS, SOURCE_LABELS, VARIANT_LABELS, type Listing } from "../types";
import { DealBadge } from "./DealBadge";

interface ScatterPoint {
  mileageKm: number;
  priceEur: number;
  year: number;
  color: string;
  listing: Listing;
}

interface PriceScatterChartProps {
  listings: Listing[];
  showTrendLine: boolean;
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
  dealScores: Map<string, DealInfo>;
}

const HIT_RADIUS = 12; // >= 24px hit target per the dataviz skill's interaction guidance
const DOT_RADIUS = 4;

export function PriceScatterChart({
  listings,
  showTrendLine,
  watchlist,
  onToggleWatchlist,
  dealScores,
}: PriceScatterChartProps) {
  const points = useMemo<ScatterPoint[]>(() => {
    const withYear = listings
      .filter((l) => l.mileageKm !== null)
      .map((l) => ({
        listing: l,
        mileageKm: l.mileageKm as number,
        priceEur: l.priceEur,
        year: l.firstRegistration ? new Date(l.firstRegistration).getFullYear() : (l.modelYear ?? 0),
      }))
      .filter((p) => p.year > 0);
    const maxYear = withYear.length ? Math.max(...withYear.map((p) => p.year)) : new Date().getFullYear();
    return withYear.map((p) => ({ ...p, color: yearColor(p.year, maxYear) }));
  }, [listings]);

  const years = useMemo(() => [...new Set(points.map((p) => p.year))].sort(), [points]);
  const maxYear = years[years.length - 1];

  const trend = useMemo(
    () => binnedMedianTrend(points.map((p) => [p.mileageKm, p.priceEur] as [number, number]), 10_000),
    [points],
  );
  const trendData = trend.map(([mileageKm, priceEur]) => ({ mileageKm, priceEur }));

  if (points.length === 0) {
    return (
      <div className="flex h-[420px] items-center justify-center rounded-lg border border-border bg-surface-1 text-sm text-muted">
        No listings match the current filters.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface-1 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs text-muted">
          Each point is a listing, coloured by registration year. Hover for detail, click to open the ad.
        </div>
        {years.length > 1 && <YearLegend years={years} maxYear={maxYear} />}
      </div>

      <ResponsiveContainer width="100%" height={420}>
        <ComposedChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--gridline)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="mileageKm"
            type="number"
            name="Mileage"
            tickFormatter={(v: number) => `${Math.round(v / 1000)}k`}
            stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            label={{ value: "Mileage (km)", position: "insideBottom", offset: -4, fill: "var(--text-muted)", fontSize: 11 }}
          />
          <YAxis
            dataKey="priceEur"
            type="number"
            name="Price"
            tickFormatter={(v: number) => `€${Math.round(v / 1000)}k`}
            stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            width={56}
          />
          <Tooltip
            cursor={{ stroke: "var(--baseline)", strokeDasharray: "3 3" }}
            content={<HoverCard onToggleWatchlist={onToggleWatchlist} watchlist={watchlist} dealScores={dealScores} />}
            trigger="hover"
          />
          {showTrendLine && (
            <Line
              data={trendData}
              dataKey="priceEur"
              xAxisId={0}
              type="monotone"
              stroke="var(--text-secondary)"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              isAnimationActive={false}
              legendType="none"
            />
          )}
          <Scatter
            data={points}
            dataKey="priceEur"
            isAnimationActive={false}
            shape={(props: unknown) => {
              const p = props as { cx: number; cy: number; payload: ScatterPoint };
              const isWatchlisted = watchlist.has(p.payload.listing.id);
              return (
                <g
                  style={{ cursor: "pointer" }}
                  onClick={() => window.open(p.payload.listing.url, "_blank", "noopener")}
                >
                  <circle cx={p.cx} cy={p.cy} r={HIT_RADIUS} fill="transparent" pointerEvents="all" />
                  {isWatchlisted && (
                    <circle
                      cx={p.cx}
                      cy={p.cy}
                      r={DOT_RADIUS + 3}
                      fill="none"
                      stroke="var(--series-1)"
                      strokeWidth={2}
                    />
                  )}
                  <circle
                    cx={p.cx}
                    cy={p.cy}
                    r={DOT_RADIUS}
                    fill={p.payload.color}
                    stroke="var(--surface-1)"
                    strokeWidth={2}
                  />
                </g>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function YearLegend({ years, maxYear }: { years: number[]; maxYear: number }) {
  const entries = yearLegendEntries(years, maxYear);
  return (
    <div className="flex shrink-0 items-center gap-2 text-[10px] text-muted">
      <span className="uppercase tracking-wide">Reg. year</span>
      <div className="flex items-center gap-1.5">
        {entries.map((e) => (
          <span key={e.label} className="flex items-center gap-1 text-secondary">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: e.color }} />
            {e.label}
          </span>
        ))}
      </div>
    </div>
  );
}

interface HoverCardProps {
  active?: boolean;
  // The trend line's points are plain {mileageKm, priceEur} - no `listing` -
  // so the payload is only *partly* ScatterPoint-shaped. Typing it honestly
  // is what makes the guard below obviously necessary rather than defensive.
  payload?: { payload: Partial<ScatterPoint> }[];
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
  dealScores: Map<string, DealInfo>;
}

function HoverCard({ active, payload, watchlist, onToggleWatchlist, dealScores }: HoverCardProps) {
  if (!active || !payload || payload.length === 0) return null;
  // This chart draws two series, and Recharts hands the tooltip whichever one
  // is under the cursor. Only the scatter carries a listing; hovering the
  // trend line used to reach `listing.id` on undefined, which threw and (with
  // no error boundary above it) blanked the whole dashboard.
  const listing = payload.find((entry) => entry?.payload?.listing)?.payload.listing;
  if (!listing) return null;
  const isWatchlisted = watchlist.has(listing.id);
  const deal = dealScores.get(listing.id);

  return (
    <div className="w-64 overflow-hidden rounded-lg border border-border bg-surface-1 shadow-xl">
      {listing.photoUrls[0] && (
        <div className="relative h-32 w-full bg-surface-2">
          <img
            src={listing.photoUrls[0]}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
          {listing.firstRegistration && (
            <span className="absolute left-2 top-2 rounded bg-surface-1/90 px-1.5 py-0.5 text-[10px] font-medium text-secondary">
              {formatYearMonth(listing.firstRegistration)}
            </span>
          )}
          {listing.isNew && (
            <span className="absolute right-2 top-2 rounded bg-status-warning px-1.5 py-0.5 text-[10px] font-semibold text-black">
              NEW
            </span>
          )}
        </div>
      )}

      <div className="p-3">
        <div className="mb-1 flex items-start justify-between gap-2">
          <p className="text-xs font-medium leading-snug text-primary">{listing.titleRaw ?? "Untitled listing"}</p>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleWatchlist(listing.id);
            }}
            className="shrink-0 text-sm"
            title={isWatchlisted ? "Remove from watchlist" : "Add to watchlist"}
          >
            {isWatchlisted ? "★" : "☆"}
          </button>
        </div>

        <div className="mb-2 grid grid-cols-2 gap-2 tabular">
          <div>
            <div className="text-[10px] uppercase text-muted">Price</div>
            <div className="text-sm font-semibold text-primary">{formatEur(listing.priceEur)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-muted">Mileage</div>
            <div className="text-sm font-semibold text-primary">
              {listing.mileageKm !== null ? formatKm(listing.mileageKm) : "—"}
            </div>
          </div>
        </div>

        <div className="mb-2 flex items-center gap-2 text-[11px] text-secondary">
          <span>{listing.country}</span>
          {listing.powerKw && <span>· {listing.powerKw} kW</span>}
        </div>

        {deal && (
          <div className="mb-2 flex items-center gap-2">
            <DealBadge deal={deal} mode="pill" />
            <DealBadge deal={deal} mode="inline" />
          </div>
        )}

        <div className="mb-2 text-[11px] text-secondary">
          {listing.daysAtCurrentPrice === 0
            ? "held at this price since today"
            : `held ${formatEur(listing.priceEur)} for ${listing.daysAtCurrentPrice} day${listing.daysAtCurrentPrice === 1 ? "" : "s"}`}
        </div>

        <div className="flex flex-wrap gap-1">
          <Pill>{SOURCE_LABELS[listing.source] ?? listing.source}</Pill>
          {listing.sellerType && <Pill>{listing.sellerType === "private" ? "Private" : "Dealer"}</Pill>}
          {listing.variant && <Pill>{VARIANT_LABELS[listing.variant] ?? listing.variant}</Pill>}
          {listing.chassisGen && <Pill>{CHASSIS_LABELS[listing.chassisGen]}</Pill>}
        </div>
      </div>
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-secondary">{children}</span>;
}
