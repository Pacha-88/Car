import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  XAxis,
  YAxis,
} from "recharts";
import { binnedMedianTrend } from "../lib/trend";
import { isOlderBucket, yearColor, yearLegendEntries } from "../lib/colors";
import type { DealInfo } from "../lib/dealScore";
import { formatKm, formatYearMonth } from "../lib/format";
import { useMoney } from "../lib/moneyContext";
import { CHASSIS_LABELS, SOURCE_LABELS, VARIANT_LABELS, listingTitle, type Listing } from "../types";
import { DealBadge } from "./DealBadge";
import { ListingPhoto } from "./ListingPhoto";

interface ScatterPoint {
  mileageKm: number;
  priceEur: number;
  year: number;
  color: string;
  /** Drawn as a hollow ring - see isOlderBucket for why colour alone won't do. */
  older: boolean;
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
  const money = useMoney();
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
    return withYear.map((p) => ({ ...p, color: yearColor(p.year, maxYear), older: isOlderBucket(p.year, maxYear) }));
  }, [listings]);

  const years = useMemo(() => [...new Set(points.map((p) => p.year))].sort(), [points]);
  const maxYear = years[years.length - 1];

  // Hover is tracked per mark rather than left to Recharts. Its tooltip
  // resolves by x-axis position, so two cars at the same mileage but very
  // different prices both showed whichever one Recharts picked for that x -
  // the "wrong photo on hover" report. Anchoring to the mark the cursor is
  // actually over is the only way to make the card always match the dot.
  const [active, setActive] = useState<{ point: ScatterPoint; x: number; y: number } | null>(null);

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

      {/* `relative` anchors the hover card, which is positioned from the
          hovered mark's own SVG coordinates. */}
      <div className="relative" onMouseLeave={() => setActive(null)}>
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
            tickFormatter={money.formatTick}
            stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            width={money.axisWidth}
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
              const isActive = active?.point.listing.id === p.payload.listing.id;
              return (
                <g
                  style={{ cursor: "pointer" }}
                  onClick={() => window.open(p.payload.listing.url, "_blank", "noopener")}
                  // Keep the existing state object when the same mark is
                  // already active, so React can bail out of the render.
                  // Storing a fresh object every time spun a loop: the
                  // re-render replaced this <g>'s children, the new node
                  // appeared under the motionless cursor, that fired
                  // mouseenter again, and so on ~15x a second for as long
                  // as the pointer rested on a dot.
                  onMouseEnter={() =>
                    setActive((cur) =>
                      cur?.point.listing.id === p.payload.listing.id
                        ? cur
                        : { point: p.payload, x: p.cx, y: p.cy },
                    )
                  }
                  onMouseLeave={() => setActive((cur) => (cur?.point.listing.id === p.payload.listing.id ? null : cur))}
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
                  {/* Ring on the hovered mark, so it's unmistakable which dot
                      the card belongs to. */}
                  {isActive && (
                    <circle
                      cx={p.cx}
                      cy={p.cy}
                      r={DOT_RADIUS + 5}
                      fill="none"
                      stroke="var(--text-primary)"
                      strokeWidth={2}
                    />
                  )}
                  <circle
                    cx={p.cx}
                    cy={p.cy}
                    r={DOT_RADIUS}
                    fill={p.payload.older ? "none" : p.payload.color}
                    stroke={p.payload.older ? p.payload.color : "var(--surface-1)"}
                    strokeWidth={2}
                  />
                </g>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>

        {active && (
          <div
            className="pointer-events-none absolute z-10"
            style={{
              // Offset from the mark, flipping near the right/bottom edges so
              // the card stays inside the plot.
              left: active.x > 900 ? undefined : active.x + 16,
              right: active.x > 900 ? 16 : undefined,
              top: active.y > 220 ? undefined : active.y + 16,
              bottom: active.y > 220 ? 16 : undefined,
            }}
          >
            <HoverCard
              point={active.point}
              watchlist={watchlist}
              onToggleWatchlist={onToggleWatchlist}
              dealScores={dealScores}
            />
          </div>
        )}
      </div>
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
            {/* The swatch mirrors the mark, so the legend teaches the
                hollow-ring encoding rather than leaving it a mystery. */}
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={
                e.older
                  ? { border: `2px solid ${e.color}` }
                  : { backgroundColor: e.color }
              }
            />
            {e.label}
          </span>
        ))}
      </div>
    </div>
  );
}

interface HoverCardProps {
  /** The mark actually under the cursor - passed straight in, rather than
   * looked up from a tooltip payload, so the card can never describe a
   * different listing than the dot the ring is drawn on. */
  point: ScatterPoint;
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
  dealScores: Map<string, DealInfo>;
}

function HoverCard({ point, watchlist, onToggleWatchlist, dealScores }: HoverCardProps) {
  const money = useMoney();
  const { listing } = point;
  const isWatchlisted = watchlist.has(listing.id);
  const deal = dealScores.get(listing.id);

  return (
    <div className="w-64 overflow-hidden rounded-lg border border-border bg-surface-1 shadow-xl">
      {listing.photoUrls[0] && (
        <div className="relative h-32 w-full bg-surface-2">
          <ListingPhoto src={listing.photoUrls[0]} />
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
          <p className="text-xs font-medium leading-snug text-primary">{listingTitle(listing)}</p>
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
            <div className="text-sm font-semibold text-primary">{money.format(listing.priceEur)}</div>
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
            : `held ${money.format(listing.priceEur)} for ${listing.daysAtCurrentPrice} day${listing.daysAtCurrentPrice === 1 ? "" : "s"}`}
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
