interface ChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
  dot?: string; // CSS color for a leading identity dot
  swatch?: string; // literal paint-color swatch (COLOUR filter) - different job than `dot`
  count?: number;
}

/** The one filter-pill look reused across every filter group. */
export function Chip({ label, active, onClick, dot, swatch, count }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "border-series-1 bg-series-1 text-white"
          : "border-border bg-surface-2/40 text-secondary hover:text-primary hover:bg-surface-2"
      }`}
    >
      {swatch && (
        <span
          className="h-2.5 w-2.5 rounded-full border border-border"
          style={{ backgroundColor: swatch }}
          aria-hidden
        />
      )}
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${active ? "ring-1 ring-white/60" : ""}`}
          style={{ backgroundColor: dot }}
          aria-hidden
        />
      )}
      <span>{label}</span>
      {count !== undefined && <span className={`tabular ${active ? "text-white/80" : "text-muted"}`}>{count}</span>}
    </button>
  );
}
