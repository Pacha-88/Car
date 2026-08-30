import { useMemo, useState } from "react";
import type { DealInfo } from "../lib/dealScore";
import { formatKm, formatYearMonth } from "../lib/format";
import { useMoney } from "../lib/moneyContext";
import { SOURCE_COLOR_VAR, SOURCE_LABELS, VARIANT_LABELS, listingTitle, type Listing, type SaleTime } from "../types";
import { DealBadge } from "./DealBadge";
import { PriceDropBadge } from "./PriceDropBadge";
import { priceChange } from "../lib/priceHistory";
import { daysListed, isSlowSeller, saleTimeFor } from "../lib/marketTime";
import { PriceSparkline } from "./PriceSparkline";
import { ListingPhoto } from "./ListingPhoto";

interface ListingGridProps {
  listings: Listing[];
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
  dealScores: Map<string, DealInfo>;
  /** The data's own clock - market time is measured against the last
   * scrape, never the reader's wall clock. */
  latestScrapeDate: string | null;
  saleTimes: SaleTime[];
}

type SortKey = "newest" | "best_deal" | "biggest_drop" | "longest_listed" | "price_asc" | "price_desc" | "mileage_asc";
const PAGE_SIZES = [25, 50, 100];

const COUNTRY_FLAGS: Record<string, string> = { DE: "🇩🇪", AT: "🇦🇹", HU: "🇭🇺", NL: "🇳🇱", BE: "🇧🇪", IT: "🇮🇹", ES: "🇪🇸", FR: "🇫🇷", LU: "🇱🇺" };

function sortListings(listings: Listing[], key: SortKey, dealScores: Map<string, DealInfo>): Listing[] {
  const copy = [...listings];
  switch (key) {
    case "best_deal":
      // Most below market first; unscored cars sort last, keeping newest order.
      return copy.sort((a, b) => (dealScores.get(a.id)?.pct ?? Infinity) - (dealScores.get(b.id)?.pct ?? Infinity));
    case "biggest_drop": {
      // Deepest cut first, then the cars nobody repriced, then the few that
      // went UP - a rise is the least interesting thing this sort can show.
      //
      // Computed once per listing rather than inside the comparator, which
      // would re-derive every car's history the O(n log n) times it is
      // compared instead of the n times it needs to be.
      const pct = new Map(copy.map((l) => [l.id, priceChange(l)?.pct ?? 0]));
      return copy.sort((a, b) => (pct.get(a.id) ?? 0) - (pct.get(b.id) ?? 0));
    }
    case "longest_listed":
      // The sitters first: a seller a month into an unsold ad is the one
      // an offer lands with.
      return copy.sort((a, b) => new Date(a.firstSeenAt).getTime() - new Date(b.firstSeenAt).getTime());
    case "price_asc":
      return copy.sort((a, b) => a.priceEur - b.priceEur);
    case "price_desc":
      return copy.sort((a, b) => b.priceEur - a.priceEur);
    case "mileage_asc":
      return copy.sort((a, b) => (a.mileageKm ?? Infinity) - (b.mileageKm ?? Infinity));
    default:
      return copy.sort((a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime());
  }
}

export function ListingGrid({ listings, watchlist, onToggleWatchlist, dealScores, latestScrapeDate, saleTimes }: ListingGridProps) {
  const [view, setView] = useState<"grid" | "list">("grid");
  const [sort, setSort] = useState<SortKey>("newest");
  const [perPage, setPerPage] = useState(50);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => sortListings(listings, sort, dealScores), [listings, sort, dealScores]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / perPage));
  const clampedPage = Math.min(page, totalPages - 1);
  const pageItems = sorted.slice(clampedPage * perPage, clampedPage * perPage + perPage);

  return (
    <div>
      {/* Sticky within the grid only: 50 cards is a long scroll, and the
          count plus the sort/view controls are what you reach for halfway
          down it. It releases as soon as the grid ends. */}
      <div className="sticky top-0 z-20 -mx-1 mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2 bg-surface-0/85 px-1 py-2 backdrop-blur-sm">
        <div className="min-w-0">
          <div className="eyebrow">Listings</div>
          <h2 className="mt-1 text-sm font-semibold leading-tight text-primary">
            <span className="numeral">{listings.length}</span>{" "}
            <span className="font-normal text-muted">matching the filters above</span>
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-1 p-0.5">
            {(["grid", "list"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={`rounded-[6px] px-2.5 py-1 font-medium capitalize transition-colors ${
                  view === v ? "bg-accent text-accent-ink" : "text-secondary hover:bg-surface-2 hover:text-primary"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-muted">
            Sort
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as SortKey);
                setPage(0);
              }}
              className="cursor-pointer rounded-lg border border-border bg-surface-1 px-2 py-1.5 font-medium text-primary transition-colors hover:border-border-strong"
            >
              <option value="newest">Newest listings first</option>
              <option value="best_deal">Best deals first</option>
              <option value="biggest_drop">Biggest price drop</option>
              <option value="longest_listed">Longest on market</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
              <option value="mileage_asc">Mileage: low to high</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-muted">
            Per page
            <select
              value={perPage}
              onChange={(e) => {
                setPerPage(Number(e.target.value));
                setPage(0);
              }}
              className="cursor-pointer rounded-lg border border-border bg-surface-1 px-2 py-1.5 font-medium text-primary transition-colors hover:border-border-strong"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {pageItems.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center text-sm text-muted">
          No listings match the current filters.
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {pageItems.map((l) => (
            <ListingCard
              key={l.id}
              listing={l}
              watchlisted={watchlist.has(l.id)}
              onToggleWatchlist={onToggleWatchlist}
              deal={dealScores.get(l.id)}
              latestScrapeDate={latestScrapeDate}
              saleTimes={saleTimes}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {pageItems.map((l) => (
            <ListingRow
              key={l.id}
              listing={l}
              watchlisted={watchlist.has(l.id)}
              onToggleWatchlist={onToggleWatchlist}
              deal={dealScores.get(l.id)}
              latestScrapeDate={latestScrapeDate}
              saleTimes={saleTimes}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-center gap-2 text-xs">
          <button
            type="button"
            disabled={clampedPage === 0}
            onClick={() => setPage(clampedPage - 1)}
            className="rounded-lg border border-border px-2.5 py-1.5 font-medium text-secondary transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-primary disabled:opacity-30 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-secondary"
          >
            ← Prev
          </button>
          <span className="numeral px-1 text-muted">
            Page {clampedPage + 1} / {totalPages}
          </span>
          <button
            type="button"
            disabled={clampedPage >= totalPages - 1}
            onClick={() => setPage(clampedPage + 1)}
            className="rounded-lg border border-border px-2.5 py-1.5 font-medium text-secondary transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-primary disabled:opacity-30 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-secondary"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

function subtitle(listing: Listing): string {
  const parts: string[] = [];
  if (listing.variant) parts.push(VARIANT_LABELS[listing.variant] ?? listing.variant);
  if (listing.color) parts.push(listing.color[0].toUpperCase() + listing.color.slice(1));
  if (listing.powerKw) parts.push(`${listing.powerKw} kW`);
  return parts.join(" · ") || "—";
}

function marketTimeTitle(listing: Listing, days: number, typical: SaleTime | null): string {
  const first = listing.firstSeenAt.slice(0, 10);
  let text = `Tracked ${days} day${days === 1 ? "" : "s"} (first seen ${first} - the ad itself may be older).`;
  if (typical) {
    text += ` Similar cars typically sell in ~${Math.round(typical.medianDays)} days (${typical.n} watched sale${
      typical.n === 1 ? "" : "s"
    }).`;
  }
  return text;
}

function ListingCard({
  listing,
  watchlisted,
  onToggleWatchlist,
  deal,
  latestScrapeDate,
  saleTimes,
}: {
  listing: Listing;
  watchlisted: boolean;
  onToggleWatchlist: (id: string) => void;
  deal: DealInfo | undefined;
  latestScrapeDate: string | null;
  saleTimes: SaleTime[];
}) {
  const money = useMoney();
  const days = daysListed(listing, latestScrapeDate);
  const typical = saleTimeFor(saleTimes, listing);
  const slow = isSlowSeller(days, typical);
  return (
    <a
      href={listing.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex flex-col overflow-hidden rounded-xl border border-border bg-surface-1 transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:border-border-strong hover:shadow-[var(--shadow-2)]"
    >
      <div className="photo-well relative aspect-[4/3] w-full overflow-hidden">
        <ListingPhoto src={listing.photoUrls[0]} withLabel />
        {/* Scrim: the badges sit on whatever the photo happens to be, and a
            white car under a white badge is unreadable without it. */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-12 bg-gradient-to-b from-black/45 to-transparent"
          aria-hidden
        />
        <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded-md bg-surface-1/85 px-1.5 py-0.5 text-[10px] font-medium text-secondary backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: SOURCE_COLOR_VAR[listing.source] }} />
          {COUNTRY_FLAGS[listing.country] ?? listing.country} {formatYearMonth(listing.firstRegistration) ?? "—"}
        </span>
        {listing.isNew && (
          <span className="absolute right-1.5 top-1.5 rounded-md bg-status-warning px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-black">
            NEW
          </span>
        )}
        <span className="absolute bottom-1.5 left-1.5">
          <DealBadge deal={deal} mode="pill" />
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            onToggleWatchlist(listing.id);
          }}
          className="absolute bottom-1.5 right-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-surface-1/85 text-xs text-secondary backdrop-blur-sm transition-colors hover:text-primary"
        >
          {watchlisted ? "★" : "☆"}
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-2.5">
        <p className="line-clamp-2 text-[11px] font-medium leading-snug text-primary">{listingTitle(listing)}</p>
        <p className="text-[10px] text-muted">
          {subtitle(listing)}
          {listing.hasFsd && <span className="ml-1 font-semibold text-secondary">· FSD</span>}
        </p>
        <div className="numeral mt-auto flex items-baseline justify-between gap-2 pt-1.5">
          <span className="text-[15px] font-semibold leading-none text-primary">{money.formatListing(listing)}</span>
          <span className="text-[10px] text-muted">
            {listing.mileageKm !== null ? formatKm(listing.mileageKm) : "—"}
            {/* Shown from two weeks: on a young ad "3 days" is noise, and
                on the day the tracker launches every card would carry it. */}
            {days !== null && days >= 14 && (
              <span title={marketTimeTitle(listing, days, typical)} className={slow ? "font-semibold text-status-warning" : ""}>
                {" "}
                · {days} d
              </span>
            )}
          </span>
        </div>
        {/* Its own row: squeezed beside the two badges it overlapped the
            deal text on narrow cards. Only repriced cars pay the height. */}
        {(listing.priceHistory?.length ?? 0) >= 2 && (
          <div className="flex justify-start pt-0.5">
            <PriceSparkline listing={listing} latestScrapeDate={latestScrapeDate} />
          </div>
        )}
        <div className="flex items-center justify-between gap-1">
          <PriceDropBadge listing={listing} compact />
          <DealBadge deal={deal} mode="inline" />
        </div>
      </div>
    </a>
  );
}

function ListingRow({
  listing,
  watchlisted,
  onToggleWatchlist,
  deal,
  latestScrapeDate,
  saleTimes,
}: {
  listing: Listing;
  watchlisted: boolean;
  onToggleWatchlist: (id: string) => void;
  deal: DealInfo | undefined;
  latestScrapeDate: string | null;
  saleTimes: SaleTime[];
}) {
  const money = useMoney();
  const days = daysListed(listing, latestScrapeDate);
  const typical = saleTimeFor(saleTimes, listing);
  const slow = isSlowSeller(days, typical);
  return (
    <a
      href={listing.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 rounded-lg border border-border bg-surface-1 p-2 transition-colors hover:border-border-strong hover:bg-surface-2"
    >
      <div className="photo-well h-14 w-20 shrink-0 overflow-hidden rounded-md">
        <ListingPhoto src={listing.photoUrls[0]} placeholderClassName="text-base" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-primary">{listingTitle(listing)}</p>
        <p className="text-[10px] text-muted">
          {SOURCE_LABELS[listing.source] ?? listing.source} · {COUNTRY_FLAGS[listing.country] ?? listing.country} ·{" "}
          {subtitle(listing)}
          {listing.hasFsd && <span className="ml-1 font-semibold text-secondary">· FSD</span>}
          {/* From a week up. The card's own comment already names the
              failure mode - "on the day the tracker launches every card
              would carry it" - and the row got no threshold at all, so on
              real day-one data all 621 rows read "· 1 day": uniform noise
              that distinguishes nothing. A week is where the numbers start
              to differ between cars. */}
          {days !== null && days >= 7 && (
            <span title={marketTimeTitle(listing, days, typical)} className={slow ? "ml-1 font-semibold text-status-warning" : "ml-1"}>
              · {days} days
            </span>
          )}
        </p>
      </div>
      {/* Bare, no wrapper spans: each component renders nothing for most
          cars, and an empty span is still a flex item - three of them cost
          the row three phantom gap-3 steps of blank space before the
          price. Their roots carry shrink-0 themselves. */}
      <PriceSparkline listing={listing} latestScrapeDate={latestScrapeDate} />
      <PriceDropBadge listing={listing} />
      <DealBadge deal={deal} mode="pill" />
      {listing.isNew && (
        <span className="shrink-0 rounded-md bg-status-warning px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-black">NEW</span>
      )}
      <div className="numeral shrink-0 text-right">
        <div className="text-sm font-semibold text-primary">{money.formatListing(listing)}</div>
        <div className="text-[10px] text-muted">{listing.mileageKm !== null ? formatKm(listing.mileageKm) : "—"}</div>
        <DealBadge deal={deal} mode="inline" />
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          onToggleWatchlist(listing.id);
        }}
        className="shrink-0 text-sm text-secondary transition-colors hover:text-primary"
      >
        {watchlisted ? "★" : "☆"}
      </button>
    </a>
  );
}
