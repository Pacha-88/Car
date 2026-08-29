import { useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  bucketTransitions,
  cheapestToOwn,
  computeDepreciationCurve,
  curveFlattensAt,
  steepestDrop,
  type DepreciationBucket,
} from "../lib/depreciation";
import { useMoney } from "../lib/moneyContext";
import { VARIANT_LABELS, type Listing, type Variant } from "../types";

interface DepreciationModuleProps {
  listings: Listing[];
}

const VARIANT_TABS: { key: Variant | "all"; label: string }[] = [
  { key: "all", label: "All variants" },
  { key: "long_range_awd", label: VARIANT_LABELS.long_range_awd },
  { key: "long_range_rwd", label: VARIANT_LABELS.long_range_rwd },
  { key: "rwd", label: VARIANT_LABELS.rwd },
  { key: "performance", label: VARIANT_LABELS.performance },
];

const MIN_BUCKET_SIZE = 10;

// One clock read for the page. Ages are bucketed by whole years here, so a
// tab left open across midnight changes nothing - and reading the clock
// during render is both impure and pointless at this granularity.
const PAGE_LOADED_AT = new Date();

/** "under_1yr" -> "under 1yr", "7yr_plus" -> "7yr+" - for axis space. */
function shortLabel(label: string): string {
  return label.replace("under_1yr", "<1yr").replace("yr_plus", "yr+");
}

/** The calendar year a bucket's cars were (roughly) registered in.
 *
 * The oldest bucket is a catch-all - every car at or past the last age -
 * so naming one year for it is a claim it cannot make. On the real Model 3
 * data that bucket holds twenty cars spanning 2019, 2018 and 2017, all
 * presented as 2019. It gets a "<=" instead. */
function bucketCalendarYear(label: string, bucketIndex: number): string {
  const year = PAGE_LOADED_AT.getFullYear() - bucketIndex;
  return label.endsWith("_plus") ? `≤${year}` : String(year);
}

export function DepreciationModule({ listings }: DepreciationModuleProps) {
  const money = useMoney();
  const [variantTab, setVariantTab] = useState<Variant | "all">("all");
  const [referenceKm, setReferenceKm] = useState(60_000);

  // Memoized: unmemoized, this was a fresh array on every render as soon as
  // a variant tab was selected, so the `input` memo below it never once hit
  // its cache and the whole curve was recomputed on every hover.
  const scoped = useMemo(
    () => (variantTab === "all" ? listings : listings.filter((l) => l.variant === variantTab)),
    [listings, variantTab],
  );
  const input = useMemo(
    () =>
      scoped
        .filter((l) => l.firstRegistration && l.mileageKm !== null)
        .map((l) => ({
          firstRegistration: new Date(l.firstRegistration as string),
          mileageKm: l.mileageKm as number,
          priceEur: l.priceEur,
        })),
    [scoped],
  );

  const buckets = useMemo(() => {
    if (input.length < 2) return [];
    try {
      return computeDepreciationCurve(input, PAGE_LOADED_AT, { referenceKm, minBucketSize: MIN_BUCKET_SIZE });
    } catch {
      return [];
    }
  }, [input, referenceKm]);

  const transitions = useMemo(() => bucketTransitions(buckets), [buckets]);
  const drop = steepestDrop(transitions);
  const flat = curveFlattensAt(transitions);
  const cheapest = cheapestToOwn(buckets, 3);
  const youngest = buckets.find((b) => !b.isThin) ?? buckets[0];
  const youngestPrice = youngest?.medianPriceEur;

  const thinBuckets = buckets.filter((b) => b.isThin);

  if (buckets.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface-1 p-4 text-sm text-muted shadow-[var(--shadow-1)]">
        Not enough listings with a known registration date and mileage to build a depreciation curve.
      </div>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-1)]">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-tight text-primary">Depreciation by model year</h2>
          <p className="mt-0.5 text-xs text-muted">
            {input.length} listings · all prices adjusted to {referenceKm.toLocaleString("de-DE")} km · band = middle
            half of each bucket (25th–75th percentile)
          </p>
        </div>
        <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-2 p-0.5">
          {VARIANT_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setVariantTab(t.key)}
              aria-pressed={variantTab === t.key}
              className={`rounded-[6px] px-2.5 py-1 text-xs font-medium transition-colors ${
                variantTab === t.key ? "bg-accent text-accent-ink" : "text-secondary hover:bg-surface-3 hover:text-primary"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <div className="px-4 pb-3 pt-3">
      <label className="mb-2 flex w-fit items-center gap-2.5">
        <span className="eyebrow">Compare at</span>
        {/* The rail is painted by this wrapper, not by the input: the shared
            .range-thumb-input rule makes the input itself transparent so the
            two-handle slider can overlay a pair of them. */}
        <span className="relative block h-4 w-36">
          <span className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-baseline" />
          <span
            className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-muted"
            style={{ left: 0, width: `${(referenceKm / 150_000) * 100}%` }}
          />
          <input
            type="range"
            min={0}
            max={150_000}
            step={5_000}
            value={referenceKm}
            onChange={(e) => setReferenceKm(Number(e.target.value))}
            className="range-thumb-input absolute inset-0 h-4 w-full"
          />
        </span>
        <span className="numeral text-[11px] font-medium text-secondary">{referenceKm.toLocaleString("de-DE")} km</span>
      </label>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_240px]">
        <div>
          <ResponsiveContainer width="100%" height={330}>
            <ComposedChart data={buckets} margin={{ top: 30, right: 24, bottom: 14, left: 0 }}>
              <CartesianGrid stroke="var(--gridline)" vertical={false} />
              <XAxis
                dataKey="label"
                interval={0}
                stroke="var(--baseline)"
                tick={(props: unknown) => {
                  const p = props as { x: number; y: number; index: number };
                  const bucket = buckets[p.index];
                  if (!bucket) return <g />;
                  return (
                    <g transform={`translate(${p.x},${p.y})`}>
                      <text textAnchor="middle" dy={12} fill="var(--text-secondary)" fontSize={11}>
                        {shortLabel(bucket.label)}
                      </text>
                      <text textAnchor="middle" dy={26} fill="var(--text-muted)" fontSize={9.5}>
                        {bucketCalendarYear(bucket.label, bucket.bucketIndex)} · n={bucket.n}
                      </text>
                    </g>
                  );
                }}
                height={44}
              />
              <YAxis
                tickFormatter={money.formatTick}
                stroke="var(--baseline)"
                tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                width={money.axisWidth}
                domain={["auto", "auto"]}
              />
              <Tooltip content={<BucketTooltip youngestPrice={youngestPrice} />} />
              {/* IQR band as a range area ([low, high] dataKey), NOT a
                  stacked pair - a stack's base layer runs from zero and
                  drags the y-domain down to 0, squashing the curve. */}
              <Area
                dataKey={(b: DepreciationBucket) => [b.p25PriceEur, b.p75PriceEur]}
                type="monotone"
                stroke="none"
                fill="var(--series-1)"
                fillOpacity={0.14}
                isAnimationActive={false}
                legendType="none"
                activeDot={false}
              />
              <Line
                dataKey="medianPriceEur"
                type="monotone"
                stroke="var(--series-1)"
                strokeWidth={2.5}
                isAnimationActive={false}
                dot={(props: unknown) => {
                  const p = props as { cx: number; cy: number; payload: DepreciationBucket; index: number };
                  return (
                    <circle
                      key={`dot-${p.index}`}
                      cx={p.cx}
                      cy={p.cy}
                      r={5}
                      fill={p.payload.isThin ? "var(--surface-1)" : "var(--series-1)"}
                      stroke="var(--series-1)"
                      strokeWidth={2}
                    />
                  );
                }}
                label={(props: unknown) => {
                  const p = props as { x: number; y: number; index: number };
                  const bucket = buckets[p.index];
                  if (!bucket) return <g />;
                  // Edge labels anchor inward so they don't clip at the plot edges.
                  const anchor = p.index === 0 ? "start" : p.index === buckets.length - 1 ? "end" : "middle";
                  const pct =
                    youngestPrice && !bucket.isThin && bucket !== youngest
                      ? Math.round((bucket.medianPriceEur / youngestPrice) * 100)
                      : null;
                  return (
                    <g key={`lbl-${p.index}`}>
                      <text
                        x={p.x}
                        y={p.y - 12}
                        textAnchor={anchor}
                        fill={bucket.isThin ? "var(--text-muted)" : "var(--text-primary)"}
                        fontSize={11}
                        fontWeight={600}
                        style={{ fontVariantNumeric: "tabular-nums" }}
                      >
                        {money.format(Math.round(bucket.medianPriceEur / 100) * 100)}
                      </text>
                      {pct !== null && (
                        <text
                          x={p.x}
                          y={p.y + 20}
                          textAnchor="middle"
                          fill="var(--text-muted)"
                          fontSize={9.5}
                          style={{ fontVariantNumeric: "tabular-nums" }}
                        >
                          {pct}%
                        </text>
                      )}
                    </g>
                  );
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
          {thinBuckets.length > 0 && (
            <p className="mt-1 text-[10px] text-muted">
              Thin (hollow dot, n&lt;{MIN_BUCKET_SIZE}, excluded from every figure to the right):{" "}
              {thinBuckets.map((b) => `${shortLabel(b.label)} (n=${b.n})`).join(", ")}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {cheapest && (
            <InsightCard
              label={`Cheapest to own · ${cheapest.horizonYears}yr`}
              // The headline names both ends, so the holding period the
              // label promises is visible rather than implied - it was the
              // gap between "· 3yr" and a silently shorter span that made
              // the old figure misleading.
              headline={`buy at ${shortLabel(cheapest.buyAtLabel).replace("_", " ")} → sell at ${shortLabel(
                cheapest.sellAtLabel,
              ).replace("_", " ")}`}
              detail={`${money.formatSigned(-Math.abs(cheapest.annualCostEur))}/yr · ${money.format(cheapest.buyPriceEur)}`}
            />
          )}
          {drop && (
            <InsightCard
              label="Steepest drop"
              headline={`${shortLabel(drop.fromLabel)} → ${shortLabel(drop.toLabel)}`}
              detail={money.formatSigned(drop.deltaEur)}
            />
          )}
          {flat && (
            <InsightCard
              label="Curve flattens"
              headline={`${shortLabel(flat.fromLabel)} → ${shortLabel(flat.toLabel)}`}
              detail={money.formatSigned(flat.deltaEur)}
            />
          )}
          {transitions.length > 0 && (
            <div>
              <div className="eyebrow mb-1.5">Cost of one more year</div>
              <div className="flex flex-col gap-1">
                {transitions.map((t) => (
                  <div key={`${t.fromLabel}-${t.toLabel}`} className="flex items-baseline gap-2 text-[11px]">
                    <span className="w-20 shrink-0 text-secondary">
                      {shortLabel(t.fromLabel)}→{shortLabel(t.toLabel)}
                    </span>
                    <span className="numeral ml-auto text-right text-primary">{money.formatSigned(t.deltaEur)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <p className="mt-3 border-t border-border pt-2.5 text-[10px] leading-relaxed text-muted">
        Prices are adjusted to the compare-at mileage using one linear price-per-km rate fit across the current selection, so
        they move with the slider above and are not what any specific car actually sold for. This compares different
        cars on one day rather than tracking one over time, and these are asking prices, not sale prices. There is no
        "new list price" reference here (no source in this project provides Tesla's new-car pricing) — percentages are
        relative to the youngest non-thin bucket, not MSRP.
      </p>
      </div>
    </section>
  );
}

function InsightCard({ label, headline, detail }: { label: string; headline: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
      <div className="eyebrow mb-1">{label}</div>
      <div className="text-sm font-medium leading-snug text-primary">{headline}</div>
      <div className="numeral mt-0.5 text-xs text-secondary">{detail}</div>
    </div>
  );
}

function BucketTooltip({
  active,
  payload,
  youngestPrice,
}: {
  active?: boolean;
  payload?: { payload: DepreciationBucket }[];
  youngestPrice?: number;
}) {
  const money = useMoney();
  if (!active || !payload || payload.length === 0) return null;
  const bucket = payload[0].payload;
  const pct = youngestPrice ? Math.round((bucket.medianPriceEur / youngestPrice) * 100) : null;
  return (
    <div className="rounded-md border border-border bg-surface-1 px-2.5 py-1.5 text-xs shadow-lg">
      <div className="font-medium text-primary">
        {shortLabel(bucket.label)} · {bucketCalendarYear(bucket.label, bucket.bucketIndex)}
      </div>
      <div className="tabular text-secondary">
        {money.format(bucket.medianPriceEur)} {pct !== null && `· ${pct}% of youngest`}
      </div>
      <div className="tabular text-[10px] text-muted">
        middle half {money.format(bucket.p25PriceEur)} – {money.format(bucket.p75PriceEur)}
      </div>
      <div className="text-[10px] text-muted">
        n={bucket.n}
        {bucket.isThin ? " (thin)" : ""}
      </div>
    </div>
  );
}
