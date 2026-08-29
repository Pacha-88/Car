/**
 * Three states, not two. A filter group where nothing is narrowed used to
 * paint every chip in the "selected" colour, so the resting dashboard was a
 * wall of accent pills that said "six active filters" when in fact none of
 * them was doing anything. `calm` is that resting look: quiet, available,
 * clearly clickable. The accent is spent only on a group you have actually
 * narrowed, where it now means something.
 */
export type ChipState = "calm" | "on" | "off";

interface ChipProps {
  label: string;
  state: ChipState;
  onClick: () => void;
  dot?: string; // CSS color for a leading identity dot
  swatch?: string; // literal paint-color swatch (COLOUR filter) - different job than `dot`
  count?: number;
  title?: string;
}

const STATE_CLASS: Record<ChipState, string> = {
  calm: "border-border bg-surface-2 text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-primary",
  on: "border-accent bg-accent text-accent-ink shadow-[var(--shadow-1)]",
  off: "border-transparent bg-transparent text-muted hover:bg-surface-2 hover:text-secondary",
};

/** The one filter-pill look reused across every filter group. */
export function Chip({ label, state, onClick, dot, swatch, count, title }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      // `state === "on"`, not `!== "off"`: a calm chip is one nobody has
      // chosen, so announcing it as pressed told a screen reader every
      // filter on the page was active at rest - the exact claim the three
      // states exist to stop the colours making.
      aria-pressed={state === "on"}
      title={title}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-[background-color,border-color,color,opacity] duration-150 ${STATE_CLASS[state]} ${
        state === "off" ? "opacity-60 hover:opacity-100" : ""
      }`}
    >
      {swatch && (
        <span
          className={`h-2.5 w-2.5 rounded-full ring-1 ${state === "on" ? "ring-black/25" : "ring-border-strong"}`}
          style={{ backgroundColor: swatch }}
          aria-hidden
        />
      )}
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${state === "on" ? "ring-2 ring-black/15" : ""}`}
          style={{ backgroundColor: dot }}
          aria-hidden
        />
      )}
      <span>{label}</span>
      {count !== undefined && (
        <span className={`numeral ${state === "on" ? "text-accent-ink/60" : "text-muted"}`}>{count}</span>
      )}
    </button>
  );
}
