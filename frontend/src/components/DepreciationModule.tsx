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

/** "under_1yr" -> "under 1yr", "7yr_plus" -> "7yr+" - for axis space. */
function shortLabel(label: string): string {
  return label.replace("under_1yr", "<1yr").replace("yr_plus", "yr+");
}

/** The calendar year a bucket's cars were (roughly) registered in. */
function bucketCalendarYear(bucketIndex: number): number {
  return new Date().getFullYear() - bucketIndex;
}

export function DepreciationModule({ listings }: DepreciationModuleProps) {
  const money = useMoney();
  const [variantTab, setVariantTab] = useState<Variant | "all">("all");
  const [referenceKm, setReferenceKm] = useState(60_000);

  const scoped = variantTab === "all" ? listings : listings.filter((l) => l.variant === variantTab);
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
      return computeDepreciationCurve(input, new Date(), { referenceKm, minBucketSize: MIN_BUCKET_SIZE });
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
      <div className="rounded-lg border border-border bg-surface-1 p-4 text-sm text-muted">
        Not enough listings with a known registration date and mileage to build a depreciation curve.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface-1 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-primary">Depreciation by model year</h2>
          <p className="text-xs text-muted">
            {input.length} listings · all prices adjusted to {referenceKm.toLocaleString("de-DE")} km · band = middle
            half of each bucket (25th–75th percentile)
          </p>
        </div>
        <div className="flex gap-1">
          {VARIANT_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setVariantTab(t.key)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                variantTab === t.key ? "bg-series-1 text-white" : "text-secondary hover:text-primary"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted">
          Compare at
          <input
            type="range"
            min={0}
            max={150_000}
            step={5_000}
            value={referenceKm}
            onChange={(e) => setReferenceKm(Number(e.target.value))}
            className="range-thumb-input relative h-4 w-32"
          />
          <span className="tabular normal-case text-secondary">{referenceKm.toLocaleString("de-DE")} km</span>
        </label>
      </div>

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
                        {bucketCalendarYear(bucket.bucketIndex)} · n={bucket.n}
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
              <div className="mb-1 text-[10px] uppercase tracking-wide text-muted">Cost of one more year</div>
              <div className="flex flex-col gap-1">
                {transitions.map((t) => (
                  <div key={`${t.fromLabel}-${t.toLabel}`} className="flex items-center gap-2 text-[11px]">
                    <span className="w-20 shrink-0 text-secondary">
                      {shortLabel(t.fromLabel)}→{shortLabel(t.toLabel)}
                    </span>
                    <span className="tabular text-primary">{money.formatSigned(t.deltaEur)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <p className="mt-3 border-t border-border pt-2 text-[10px] leading-relaxed text-muted">
        Prices are adjusted to the compare-at mileage using one linear price-per-km rate fit across the current selection, so
        they move with the slider above and are not what any specific car actually sold for. This compares different
        cars on one day rather than tracking one over time, and these are asking prices, not sale prices. There is no
        "new list price" reference here (no source in this project provides Tesla's new-car pricing) — percentages are
        relative to the youngest non-thin bucket, not MSRP.
      </p>
    </div>
  );
}

function InsightCard({ label, headline, detail }: { label: string; headline: string; detail: string }) {
  return (
    <div className="rounded-md bg-surface-2 p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className="text-sm font-medium text-primary">{headline}</div>
      <div className="text-xs tabular text-secondary">{detail}</div>
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
        {shortLabel(bucket.label)} · {bucketCalendarYear(bucket.bucketIndex)}
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
