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
  // Which input is on top decides which thumb the mouse can grab when the
  // two overlap. DOM order puts hi above, which dies in one reachable
  // corner: drag the min handle to the far end and both thumbs stack at
  // max - the grabbable one is hi, clamped against lo, and lo is buried,
  // so no mouse drag can ever move the slider again (reproduced; only
  // Reset all or the keyboard recovered it). When the pair sits in the
  // upper half of the track, lo goes on top instead - at a cluster the
  // reachable thumb is then always the one with room to move.
  const loOnTop = (lo + hi) / 2 > (min + max) / 2;

  return (
    <div className="w-full min-w-[190px] max-w-[260px] flex-1">
      <div className="mb-1.5 flex items-center justify-between gap-4">
        <span className="eyebrow">{label}</span>
        <span className="numeral text-[11px] font-medium text-secondary">
          {formatValue(lo)} – {formatValue(hi)}
        </span>
      </div>
      <div className="relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-baseline" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-muted"
          style={{ left: `${loPct}%`, right: `${100 - hiPct}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={lo}
          aria-label={`${label} minimum`}
          onChange={(e) => {
            const next = Math.min(Number(e.target.value), hi);
            onChange([next, hi]);
          }}
          className="range-thumb-input absolute inset-x-0 top-0 h-4 w-full"
          style={loOnTop ? { zIndex: 2 } : undefined}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={hi}
          aria-label={`${label} maximum`}
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
