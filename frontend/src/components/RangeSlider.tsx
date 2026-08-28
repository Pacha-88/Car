interface RangeSliderProps {
  label: string;
  min: number;
  max: number;
  value: [number, number];
  onChange: (value: [number, number]) => void;
  formatValue: (v: number) => string;
  step?: number;
}

/** Two overlaid native range inputs - each track is transparent (only the
 * thumb paints), and pointer-events are re-enabled on the thumb only, so
 * both ends stay independently draggable despite sharing the same box. */
export function RangeSlider({ label, min, max, value, onChange, formatValue, step = 1 }: RangeSliderProps) {
  const [lo, hi] = value;
  const range = Math.max(max - min, 1);
  const loPct = ((lo - min) / range) * 100;
  const hiPct = ((hi - min) / range) * 100;

  return (
    <div className="min-w-[180px]">
      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-muted">
        <span>{label}</span>
        <span className="tabular normal-case text-secondary">
          {formatValue(lo)} – {formatValue(hi)}
        </span>
      </div>
      <div className="relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-baseline" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-series-1"
          style={{ left: `${loPct}%`, right: `${100 - hiPct}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => {
            const next = Math.min(Number(e.target.value), hi);
            onChange([next, hi]);
          }}
          className="range-thumb-input absolute inset-x-0 top-0 h-4 w-full"
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => {
            const next = Math.max(Number(e.target.value), lo);
            onChange([lo, next]);
          }}
          className="range-thumb-input absolute inset-x-0 top-0 h-4 w-full"
        />
      </div>
    </div>
  );
}
