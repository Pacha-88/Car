import { memo, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  CartesianGrid,
  Customized,
  Line,
  ComposedChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
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
  /** Newest registration year across the whole model, filters ignored. The
   * year palette is anchored to it so a car keeps its colour no matter what
   * is filtered out around it. */
  paletteMaxYear: number;
  showTrendLine: boolean;
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
  dealScores: Map<string, DealInfo>;
}

const HIT_RADIUS = 12; // >= 24px hit target per the dataviz skill's interaction guidance
const DOT_RADIUS = 4;
/** w-64 on the card below, plus a little breathing room. */
const HOVER_CARD_WIDTH = 264;

export function PriceScatterChart({
  listings,
  paletteMaxYear,
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
        year: l.firstRegistration ? Number(l.firstRegistration.slice(0, 4)) : (l.modelYear ?? 0),
      }))
      .filter((p) => p.year > 0);
    return withYear.map((p) => ({
      ...p,
      color: yearColor(p.year, paletteMaxYear),
      older: isOlderBucket(p.year, paletteMaxYear),
    }));
  }, [listings, paletteMaxYear]);

  // The legend lists the years actually on screen, but keyed to the same
  // model-wide anchor as the marks, so its swatches always match them.
  const years = useMemo(() => [...new Set(points.map((p) => p.year))].sort(), [points]);
  const maxYear = paletteMaxYear;

  // Hover is tracked per mark rather than left to Recharts. Its tooltip
  // resolves by x-axis position, so two cars at the same mileage but very
  // different prices both showed whichever one Recharts picked for that x -
  // the "wrong photo on hover" report. Anchoring to the mark the cursor is
  // actually over is the only way to make the card always match the dot.
  //
  // And it is tracked by ONE handler on the container, not one per mark.
  // At live scale this chart draws 2.000+ points; per-mark <g> handlers
  // meant hovering re-rendered every mark (the ring was part of each
  // mark's render) and cost ~2 seconds per hover. The marks render once
  // per data change and record their pixel positions; the container's
  // mousemove finds the nearest recorded mark, and the ring and card are
  // overlays that never touch the chart itself.
  const [active, setActive] = useState<{ point: ScatterPoint; x: number; y: number; plotW: number; plotH: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // One stable map for the marks' pixel positions; DotsLayer rewrites it in
  // full on every chart render, so it always matches what is on screen.
  const [positions] = useState(() => new Map<string, { cx: number; cy: number; point: ScatterPoint }>());

  useEffect(() => {
    if (!import.meta.env.DEV) return;
    // Debug handle for the Playwright checks - dev server only. positions
    // and wrapRef are stable for the component's life, so once is enough.
    (window as unknown as Record<string, unknown>).__scatterDebug = {
      size: () => positions.size,
      maxCx: () => Math.max(0, ...[...positions.values()].map((m) => m.cx)),
      rectLeft: () => wrapRef.current?.querySelector("svg.recharts-surface")?.getBoundingClientRect().left,
      nearest: (x: number, y: number) => {
        let bd = Infinity;
        for (const m of positions.values()) bd = Math.min(bd, Math.hypot(m.cx - x, m.cy - y));
        return bd;
      },
    };
  }, [positions]);

  const nearestMark = (e: MouseEvent) => {
    const svg = wrapRef.current?.querySelector("svg.recharts-surface");
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    let best: { cx: number; cy: number; point: ScatterPoint } | null = null;
    let bestDistance = HIT_RADIUS; // >= 24px hit target, same as the old per-mark circle
    for (const mark of positions.values()) {
      const d = Math.hypot(mark.cx - x, mark.cy - y);
      if (d <= bestDistance) {
        bestDistance = d;
        best = mark;
      }
    }
    if (!best) return null;
    // The plot's real size rides along so the hover card can flip against
    // the edge that actually exists, not a hardcoded one.
    return { ...best, plotW: rect.width, plotH: rect.height };
  };

  const trend = useMemo(
    () => binnedMedianTrend(points.map((p) => [p.mileageKm, p.priceEur] as [number, number]), 10_000),
    [points],
  );
  const trendData = trend.map(([mileageKm, priceEur]) => ({ mileageKm, priceEur }));

  if (points.length === 0) {
    return (
      <div className="flex h-[420px] items-center justify-center rounded-xl border border-border bg-surface-1 text-sm text-muted shadow-[var(--shadow-1)]">
        No listings match the current filters.
      </div>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-1)]">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="title-tick text-sm font-semibold leading-tight text-primary">Price vs mileage</h2>
          <p className="mt-0.5 pl-2.5 text-xs text-muted">
            Each point is a listing, coloured by registration year. Hover for detail, click to open the ad.
          </p>
        </div>
        {years.length > 1 && <YearLegend years={years} maxYear={maxYear} />}
      </header>
      <div className="px-4 pb-3 pt-3">

      {/* `relative` anchors the hover card, which is positioned from the
          hovered mark's own SVG coordinates. */}
      <div
        ref={wrapRef}
        className="relative"
        style={{ cursor: active ? "pointer" : undefined }}
        onMouseLeave={() => setActive(null)}
        onMouseMove={(e) => {
          const mark = nearestMark(e);
          // Keep the existing state object for the mark that is already
          // active, so React can bail out - a fresh object per move once
          // spun a render loop under a motionless cursor.
          setActive((cur) => {
            if (!mark) return null;
            return cur?.point.listing.id === mark.point.listing.id
              ? cur
              : { point: mark.point, x: mark.cx, y: mark.cy, plotW: mark.plotW, plotH: mark.plotH };
          });
        }}
        onClick={(e) => {
          const mark = nearestMark(e);
          if (mark) window.open(mark.point.listing.url, "_blank", "noopener");
        }}
      >
      <ChartBody
        points={points}
        trendData={trendData}
        showTrendLine={showTrendLine}
        watchlist={watchlist}
        formatTick={money.formatTick}
        axisWidth={money.axisWidth}
        positions={positions}
      />

        {active && (
          <svg
            className="pointer-events-none absolute z-10"
            style={{ left: active.x - DOT_RADIUS - 7, top: active.y - DOT_RADIUS - 7 }}
            width={(DOT_RADIUS + 7) * 2}
            height={(DOT_RADIUS + 7) * 2}
          >
            {/* Ring on the hovered mark, so it's unmistakable which dot the
                card belongs to - drawn as an overlay precisely so hovering
                never re-renders the 2.000-mark chart underneath. */}
            <circle
              cx={DOT_RADIUS + 7}
              cy={DOT_RADIUS + 7}
              r={DOT_RADIUS + 5}
              fill="none"
              stroke="var(--text-primary)"
              strokeWidth={2}
            />
          </svg>
        )}
        {active && (
          <div
            // Pass-through on purpose: an interactive card parks a 256px
            // rectangle over the plot and blocks re-hovering every dot under
            // it (measured: 2 of 10 probe points). Hover keeps working
            // through the card - whatever dot is nearest when you click is
            // the ad that opens, and the visible card names exactly that
            // dot. The one real control, the watchlist star, is its own
            // pointer-events island below.
            className="pointer-events-none absolute z-10"
            style={{
              // Offset from the mark, flipped when the card would not fit on
              // that side. Measured against the plot's own size at hover
              // time - these were hardcoded (x > 900) and on a 1024px window
              // the rightmost dot put the card 185px past the viewport.
              left: active.x + 16 + HOVER_CARD_WIDTH > active.plotW ? undefined : active.x + 16,
              right: active.x + 16 + HOVER_CARD_WIDTH > active.plotW ? 16 : undefined,
              top: active.y > active.plotH / 2 ? undefined : active.y + 16,
              bottom: active.y > active.plotH / 2 ? 16 : undefined,
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
    </section>
  );
}

/** Pad a data range by 6% on each side and snap both ends outward to a
 * round step (~5 ticks), so the axis reads in whole numbers without the
 * marks touching the frame. Never dips below zero - a negative asking
 * price is not a thing. */
function niceDomain(lo: number, hi: number): [number, number] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi <= lo) {
    // One listing, or several priced identically. A domain one unit wide
    // rounded every tick to the same string - four rows of "12,7M Ft" up
    // the axis - so open it to +-10% of the value instead.
    const half = Math.abs(hi) * 0.1 || 1;
    lo = hi - half;
    hi = hi + half;
  }
  const pad = (hi - lo) * 0.06;
  const rawStep = (hi - lo + 2 * pad) / 5;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep) ?? 10 * magnitude;
  return [Math.max(0, Math.floor((lo - pad) / step) * step), Math.ceil((hi + pad) / step) * step];
}

/** The Recharts subtree, memoized: 2.000+ marks make it the expensive part
 * of the page, and nothing about hovering may touch it. It re-renders only
 * when the data, the watchlist, the trend toggle or the currency changes.
 * Marks record their pixel positions into `positions` as they render, which
 * is what the container's single mousemove handler searches. */
const ChartBody = memo(function ChartBody({
  points,
  trendData,
  showTrendLine,
  watchlist,
  formatTick,
  axisWidth,
  positions,
}: {
  points: ScatterPoint[];
  trendData: { mileageKm: number; priceEur: number }[];
  showTrendLine: boolean;
  watchlist: Set<string>;
  formatTick: (v: number) => string;
  axisWidth: number;
  positions: Map<string, { cx: number; cy: number; point: ScatterPoint }>;
}) {
  // Explicit domains: the dots are no longer a Recharts series (see below),
  // so the axes cannot infer their extent. Rounded up to the tick rhythm
  // the automatic domain used to produce.
  const xMax = useMemo(() => {
    const top = Math.max(...points.map((p) => p.mileageKm), 1);
    // +1 before snapping so a maximum that already sits on a tick boundary
    // still gets a step of headroom - otherwise that car is drawn exactly
    // on the right frame and half of its dot is clipped away.
    return Math.ceil((top + 1) / 25_000) * 25_000;
  }, [points]);
  // A dot plot has no baseline to grow from, so - unlike a bar chart - it
  // is not obliged to include zero, and forcing it wasted the bottom 60% of
  // the plot on an empty band no listing will ever fall in. The domain is
  // the data's own range, padded and snapped to a round tick step.
  const yDomain = useMemo(() => {
    const prices = points.map((p) => p.priceEur);
    return niceDomain(Math.min(...prices), Math.max(...prices));
  }, [points]);
  return (
    <ResponsiveContainer width="100%" height={420}>
        <ComposedChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--gridline)" strokeDasharray="0" vertical={false} />
          <XAxis
            dataKey="mileageKm"
            type="number"
            domain={[0, xMax]}
            allowDataOverflow
            name="Mileage"
            tickFormatter={(v: number) => `${Math.round(v / 1000)}k`}
            stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            label={{ value: "Mileage (km)", position: "insideBottom", offset: -4, fill: "var(--text-muted)", fontSize: 11 }}
          />
          <YAxis
            dataKey="priceEur"
            type="number"
            domain={yDomain}
            allowDataOverflow
            name="Price"
            tickFormatter={formatTick}
            stroke="var(--baseline)"
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            width={axisWidth}
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
          {/* The dots. NOT a Recharts <Scatter>: that renders one React
              element per mark, and at live scale (2.000+ cars) every filter
              click paid for building and reconciling all of them - measured
              at ~3s per toggle. All dots of one colour are one merged <path>
              instead (six paths total), positioned straight off the axis
              scales; per-dot hit-testing lives in the container's single
              mousemove handler via the `positions` map filled here. */}
          <Customized component={DotsLayer} points={points} watchlist={watchlist} positions={positions} />
        </ComposedChart>
    </ResponsiveContainer>
  );
});


/** The dots. NOT a Recharts <Scatter>: that renders one React element per
 * mark, and at live scale (2.000+ cars) every filter click paid for
 * building and reconciling all of them - measured at ~3s per toggle. All
 * dots of one colour are one merged <path> instead (six paths total),
 * positioned straight off the axis scales; per-dot hit-testing lives in
 * the container's single mousemove handler via the `positions` map filled
 * here as a render side effect (recomputed on every chart render, so it
 * always matches what is on screen). */
function DotsLayer({
  points,
  watchlist,
  positions,
}: {
  points: ScatterPoint[];
  watchlist: Set<string>;
  positions: Map<string, { cx: number; cy: number; point: ScatterPoint }>;
}) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  if (!xScale || !yScale) return null;
  const solid = new Map<string, string[]>();
  const hollow = new Map<string, string[]>();
  const watchRings: { cx: number; cy: number }[] = [];
  positions.clear();
  for (const point of points) {
    const cx = xScale(point.mileageKm);
    const cy = yScale(point.priceEur);
    if (cx === undefined || cy === undefined) continue;
    positions.set(point.listing.id, { cx, cy, point });
    const r = DOT_RADIUS;
    const d = `M ${cx - r} ${cy} a ${r} ${r} 0 1 0 ${r * 2} 0 a ${r} ${r} 0 1 0 ${-r * 2} 0`;
    const bucket = point.older ? hollow : solid;
    const paths = bucket.get(point.color);
    if (paths) paths.push(d);
    else bucket.set(point.color, [d]);
    if (watchlist.has(point.listing.id)) watchRings.push({ cx, cy });
  }
  const maxCx = Math.max(0, ...[...positions.values()].map((m) => m.cx));
  return (
    <g data-dots={positions.size} data-max-cx={Math.round(maxCx)}>
      {[...solid.entries()].map(([color, ds]) => (
        <path key={color} d={ds.join(" ")} fill={color} stroke="var(--surface-1)" strokeWidth={2} />
      ))}
      {[...hollow.entries()].map(([color, ds]) => (
        <path key={`h-${color}`} d={ds.join(" ")} fill="none" stroke={color} strokeWidth={2} />
      ))}
      {watchRings.map((ring, i) => (
        <circle key={i} cx={ring.cx} cy={ring.cy} r={DOT_RADIUS + 3} fill="none" stroke="var(--series-1)" strokeWidth={2} />
      ))}
    </g>
  );
}


function YearLegend({ years, maxYear }: { years: number[]; maxYear: number }) {
  const entries = yearLegendEntries(years, maxYear);
  return (
    // min-w-0 + wrap, not shrink-0: six year entries in one unshrinkable
    // row were wider than a phone - the one element pushing the whole page
    // into horizontal scroll at 375px (413px of it). The chips wrap into
    // rows instead, inside their own box.
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-[10px] text-muted">
      <span className="eyebrow">Reg. year</span>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-border bg-surface-2 px-2 py-1">
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
    <div className="w-64 overflow-hidden rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-2)]">
      {listing.photoUrls[0] && (
        <div className="photo-well relative h-32 w-full">
          <ListingPhoto src={listing.photoUrls[0]} withLabel />
          {listing.firstRegistration && (
            <span className="absolute left-2 top-2 rounded-md bg-surface-1/85 px-1.5 py-0.5 text-[10px] font-medium text-secondary backdrop-blur-sm">
              {formatYearMonth(listing.firstRegistration)}
            </span>
          )}
          {listing.isNew && (
            <span className="absolute right-2 top-2 rounded-md bg-status-warning px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-black">
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
            // The one interactive island on a pass-through card. Its own
            // mousemove stops too, or sliding onto the star would re-target
            // the nearest dot underneath and yank the card away mid-click.
            onMouseMove={(e) => e.stopPropagation()}
            className="pointer-events-auto shrink-0 text-sm"
            title={isWatchlisted ? "Remove from watchlist" : "Add to watchlist"}
          >
            {isWatchlisted ? "★" : "☆"}
          </button>
        </div>

        <div className="mb-2 grid grid-cols-2 gap-2 tabular">
          <div>
            <div className="text-[10px] uppercase text-muted">Price</div>
            <div className="text-sm font-semibold text-primary">{money.formatListing(listing)}</div>
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
            : `held ${money.formatListing(listing)} for ${listing.daysAtCurrentPrice} day${listing.daysAtCurrentPrice === 1 ? "" : "s"}`}
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
