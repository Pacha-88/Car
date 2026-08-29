import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useMoney } from "../lib/moneyContext";
import type { MarketDay, Model } from "../types";

const WINDOWS = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 0, label: "All" },
];

/** Fewer than this and a "trend" is two dots and a straight line between
 * them. The history fills in one day per scheduled run. */
const MIN_DAYS = 3;

/** Below this a move is rounding, not a direction, and colouring it green
 * or amber would claim a signal that isn't there. */
const FLAT = 0.002;

/** A missed day happens; two in a row means the record actually stopped,
 * and the line should say so rather than bridging it. */
const GAP_BREAK_MS = 2.5 * 86_400_000;

// Read once at module load. The window cutoff only needs day granularity,
// and a clock call inside render is impure - the same props would produce
// a different window on a re-render that happened to cross midnight.
const LOADED_AT = Date.now();

interface MarketTrendChartProps {
  history: MarketDay[];
  model: Model;
}

export function MarketTrendChart({ history, model }: MarketTrendChartProps) {
  const money = useMoney();
  const [windowDays, setWindowDays] = useState(30);

  const forModel = useMemo(() => history.filter((d) => d.model === model), [history, model]);

  const days = useMemo(() => {
    if (windowDays === 0) return forModel;
    const cutoff = LOADED_AT - windowDays * 86_400_000;
    return forModel.filter((d) => new Date(`${d.date}T12:00:00`).getTime() >= cutoff);
  }, [forModel, windowDays]);

  // Plotted against real time, with the line cut wherever the record has
  // a hole. On a category axis - recharts' default for a string dataKey -
  // every point is one step wide whatever the date says, so a month the
  // scraper missed was drawn one day wide with the line running straight
  // through it: a chart claiming daily observation of a month nobody
  // looked at. Holes are not hypothetical here. A failed run leaves one,
  // and so does market_history itself, which drops any day that saw fewer
  // than a handful of cars.
  const series = useMemo(() => {
    const out: { t: number; medianEur: number | null; day: MarketDay | null }[] = [];
    days.forEach((d, i) => {
      const t = dayStart(d.date);
      const previous = i > 0 ? dayStart(days[i - 1].date) : null;
      if (previous !== null && t - previous > GAP_BREAK_MS) {
        // A null between the two ends is what breaks the stroke; recharts
        // joins across nulls only when told to, and it is not told to.
        out.push({ t: (previous + t) / 2, medianEur: null, day: null });
      }
      out.push({ t, medianEur: d.medianEur, day: d });
    });
    return out;
  }, [days]);

  // Both numbers are rebased to the start of the window being looked at, so
  // a percentage always means "since the left edge of this chart" rather
  // than since whenever tracking happened to begin.
  const move = useMemo(() => {
    if (days.length < 2) return null;
    const first = days[0];
    const last = days[days.length - 1];
    return {
      median: first.medianEur > 0 ? last.medianEur / first.medianEur - 1 : null,
      // Moved only by cars listed on both of two consecutive days, so
      // arrivals and sales cannot move it. Usually the more honest of the
      // two, and the reason it is shown next to the median rather than
      // instead of it.
      index: first.index > 0 ? last.index / first.index - 1 : null,
      fromEur: first.medianEur,
      toEur: last.medianEur,
    };
  }, [days]);

  // The band the line is drawn in. Left to itself the axis would fit the
  // p25-p75 spread, which is ten times the size of the movement and would
  // render every trend as a flat line.
  const domain = useMemo<[number, number]>(() => {
    if (!days.length) return [0, 1];
    const values = days.map((d) => d.medianEur);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = Math.max((hi - lo) * 0.35, hi * 0.01);
    return [lo - pad, hi + pad];
  }, [days]);

  const windowText = windowDays === 0 ? "the whole record" : `the last ${windowDays} days`;

  const header = (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border px-4 py-2.5">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold leading-tight text-primary">Market movement</h2>
        <p className="mt-0.5 text-xs text-muted">
          Every {model === "model_y" ? "Model Y" : "Model 3"} tracked, sold ones included — not the filters above.
        </p>
      </div>
      <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-2 p-0.5">
        {WINDOWS.map((w) => (
          <button
            key={w.days}
            type="button"
            onClick={() => setWindowDays(w.days)}
            aria-pressed={windowDays === w.days}
            className={`rounded-[6px] px-2.5 py-1 text-xs font-medium transition-colors ${
              windowDays === w.days
                ? "bg-accent text-accent-ink"
                : "text-secondary hover:bg-surface-3 hover:text-primary"
            }`}
          >
            {w.label}
          </button>
        ))}
      </div>
    </header>
  );

  if (days.length < MIN_DAYS) {
    // Two different nothings. A run that has only happened twice has no
    // trend to draw yet; a record that stops before this window began has
    // one, just not here - and telling that user "not enough history" while
    // hiding the selector leaves them in a dead end with the way out
    // removed.
    const staleWindow = forModel.length >= MIN_DAYS;
    return (
      <section className="rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-1)]">
        {header}
        <p className="px-4 py-6 text-center text-sm text-muted">
          {staleWindow ? (
            <>
              Nothing recorded in {windowText} — the {forModel.length} days on record are older than that. Try “All”.
            </>
          ) : (
            <>
              Not enough history yet — this fills in one day per scrape.
              {forModel.length > 0 && ` ${forModel.length} day${forModel.length === 1 ? "" : "s"} recorded so far.`}
            </>
          )}
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-surface-1 shadow-[var(--shadow-1)]">
      {header}

      <div className="px-4 pb-3 pt-3">
        {/* The big number is the median's own move, so it says exactly what
            the line below it draws. The mix-proof index sits beside it
            rather than replacing it: it is the better answer to "did
            prices move?", but it is a different series, and a headline
            that disagrees with its own chart is worse than a longer one. */}
        <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={`numeral text-[26px] font-semibold leading-none ${toneFor(move?.median)}`}>
            {percent(move?.median)}
          </span>
          <span className="text-xs text-muted">
            median asking price over {windowText}
            {move && (
              <>
                {" · "}
                <span className="numeral text-secondary">
                  {money.format(move.fromEur)} → {money.format(move.toEur)}
                </span>
              </>
            )}
          </span>
          <span className="ml-auto text-xs text-muted">
            <span className={`numeral font-medium ${toneFor(move?.index)}`}>{percent(move?.index)}</span> counting only
            cars on sale the whole time
          </span>
        </div>

        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={series} margin={{ top: 6, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--gridline)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              stroke="var(--baseline)"
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              tickFormatter={(t: number) => shortDate(t)}
              minTickGap={28}
            />
            <YAxis
              tickFormatter={money.formatTick}
              stroke="var(--baseline)"
              tick={{ fill: "var(--text-muted)", fontSize: 11 }}
              width={money.axisWidth}
              domain={domain}
            />
            <Tooltip content={<MarketTooltip />} cursor={{ stroke: "var(--baseline)" }} />
            <Line
              dataKey="medianEur"
              type="monotone"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/** Local midnight for an ISO date, so a point sits on its own day
 * whatever the reader's timezone. */
function dayStart(iso: string): number {
  return new Date(`${iso}T00:00:00`).getTime();
}

function shortDate(t: number): string {
  const d = new Date(t);
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

/** Down is good here: this is a page about buying one. */
function toneFor(value: number | null | undefined): string {
  if (value === null || value === undefined || Math.abs(value) < FLAT) return "text-secondary";
  return value < 0 ? "text-status-good" : "text-status-warning";
}

function MarketTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: { day: MarketDay | null } }[];
}) {
  const money = useMoney();
  if (!active || !payload?.length) return null;
  // The break inserted across a hole in the record carries no day, and
  // there is nothing truthful to say about a date nobody scraped.
  const day = payload[0].payload.day;
  if (!day) return null;
  return (
    <div className="rounded-md border border-border bg-surface-1 px-2.5 py-1.5 text-xs shadow-lg">
      <div className="font-medium text-primary">{day.date}</div>
      <div className="numeral text-secondary">
        {money.format(day.medianEur)} median · {day.n} on sale
      </div>
      <div className="numeral text-[10px] text-muted">
        middle half {money.format(day.p25Eur)} – {money.format(day.p75Eur)}
      </div>
    </div>
  );
}
