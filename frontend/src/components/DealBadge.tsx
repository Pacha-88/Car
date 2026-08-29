import { DEAL_TIER_COLOR, DEAL_TIER_LABEL, type DealInfo } from "../lib/dealScore";
import { formatPctSigned } from "../lib/format";

/**
 * How a listing's price compares to the market for a genuinely similar car.
 * Two presentations of the same DealInfo:
 *
 *  - "pill": a solid coloured badge, shown only for actual deals (great/good),
 *    used as an overlay on the listing photo where it needs to catch the eye.
 *  - "inline": a compact "−14% vs market" line for every scored listing,
 *    used in the price column and the hover card, where context already exists.
 */
export function DealBadge({ deal, mode }: { deal: DealInfo | undefined; mode: "pill" | "inline" }) {
  if (!deal) return null;

  if (mode === "pill") {
    if (deal.tier !== "great" && deal.tier !== "good") return null;
    return (
      <span
        className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
        style={{ backgroundColor: DEAL_TIER_COLOR[deal.tier] }}
        title={`${formatPctSigned(deal.pct)} vs the market for a similar car (variant, mileage and age)`}
      >
        {DEAL_TIER_LABEL[deal.tier]} · {formatPctSigned(deal.pct)}
      </span>
    );
  }

  return (
    <span
      className="tabular text-[10px] font-medium"
      style={{ color: DEAL_TIER_COLOR[deal.tier] }}
      title={`${formatPctSigned(deal.pct)} vs the market for a similar car (variant, mileage and age)`}
    >
      {formatPctSigned(deal.pct)} vs market
    </span>
  );
}
