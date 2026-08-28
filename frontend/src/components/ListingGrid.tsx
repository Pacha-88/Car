import { useMemo, useState } from "react";
import { formatEur, formatKm, formatYearMonth } from "../lib/format";
import { SOURCE_COLOR_VAR, SOURCE_LABELS, VARIANT_LABELS, type Listing } from "../types";

interface ListingGridProps {
  listings: Listing[];
  watchlist: Set<string>;
  onToggleWatchlist: (id: string) => void;
}

type SortKey = "newest" | "price_asc" | "price_desc" | "mileage_asc";
const PAGE_SIZES = [25, 50, 100];

const COUNTRY_FLAGS: Record<string, string> = { DE: "🇩🇪", AT: "🇦🇹", HU: "🇭🇺", NL: "🇳🇱", BE: "🇧🇪", IT: "🇮🇹", ES: "🇪🇸", FR: "🇫🇷", LU: "🇱🇺" };

function sortListings(listings: Listing[], key: SortKey): Listing[] {
  const copy = [...listings];
  switch (key) {
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

export function ListingGrid({ listings, watchlist, onToggleWatchlist }: ListingGridProps) {
  const [view, setView] = useState<"grid" | "list">("grid");
  const [sort, setSort] = useState<SortKey>("newest");
  const [perPage, setPerPage] = useState(50);
  const [page, setPage] = useState(0);

  const sorted = useMemo(() => sortListings(listings, sort), [listings, sort]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / perPage));
  const clampedPage = Math.min(page, totalPages - 1);
  const pageItems = sorted.slice(clampedPage * perPage, clampedPage * perPage + perPage);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-primary">
          Listings <span className="font-normal text-muted">{listings.length} matching the filters above</span>
        </h2>
        <div className="flex items-center gap-3 text-xs">
          <div className="flex overflow-hidden rounded-md border border-border">
            {(["grid", "list"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={`px-2.5 py-1 capitalize ${view === v ? "bg-series-1/20 text-primary" : "text-secondary hover:text-primary"}`}
              >
                {v}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-secondary">
            Sort
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value as SortKey);
                setPage(0);
              }}
              className="rounded-md border border-border bg-surface-1 px-1.5 py-1 text-primary"
            >
              <option value="newest">Newest listings first</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
              <option value="mileage_asc">Mileage: low to high</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-secondary">
            Per page
            <select
              value={perPage}
              onChange={(e) => {
                setPerPage(Number(e.target.value));
                setPage(0);
              }}
              className="rounded-md border border-border bg-surface-1 px-1.5 py-1 text-primary"
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
        <div className="rounded-lg border border-border bg-surface-1 p-6 text-center text-sm text-muted">
          No listings match the current filters.
        </div>
      ) : view === "grid" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {pageItems.map((l) => (
            <ListingCard key={l.id} listing={l} watchlisted={watchlist.has(l.id)} onToggleWatchlist={onToggleWatchlist} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {pageItems.map((l) => (
            <ListingRow key={l.id} listing={l} watchlisted={watchlist.has(l.id)} onToggleWatchlist={onToggleWatchlist} />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-center gap-2 text-xs">
          <button
            type="button"
            disabled={clampedPage === 0}
            onClick={() => setPage(clampedPage - 1)}
            className="rounded-md border border-border px-2 py-1 text-secondary disabled:opacity-30"
          >
            ← Prev
          </button>
          <span className="tabular text-muted">
            Page {clampedPage + 1} / {totalPages}
          </span>
          <button
            type="button"
            disabled={clampedPage >= totalPages - 1}
            onClick={() => setPage(clampedPage + 1)}
            className="rounded-md border border-border px-2 py-1 text-secondary disabled:opacity-30"
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

function ListingCard({
  listing,
  watchlisted,
  onToggleWatchlist,
}: {
  listing: Listing;
  watchlisted: boolean;
  onToggleWatchlist: (id: string) => void;
}) {
  return (
    <a
      href={listing.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex flex-col overflow-hidden rounded-lg border border-border bg-surface-1 transition-colors hover:border-series-1/50"
    >
      <div className="relative aspect-[4/3] w-full bg-surface-2">
        {listing.photoUrls[0] ? (
          <img
            src={listing.photoUrls[0]}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-2xl text-muted">🚗</div>
        )}
        <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded bg-surface-1/90 px-1.5 py-0.5 text-[10px] font-medium text-secondary">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: SOURCE_COLOR_VAR[listing.source] }} />
          {COUNTRY_FLAGS[listing.country] ?? listing.country} {formatYearMonth(listing.firstRegistration) ?? "—"}
        </span>
        {listing.isNew && (
          <span className="absolute right-1.5 top-1.5 rounded bg-status-warning px-1.5 py-0.5 text-[10px] font-semibold text-black">
            NEW
          </span>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            onToggleWatchlist(listing.id);
          }}
          className="absolute bottom-1.5 right-1.5 rounded-full bg-surface-1/90 px-1.5 py-0.5 text-xs"
        >
          {watchlisted ? "★" : "☆"}
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-2">
        <p className="line-clamp-2 text-[11px] font-medium leading-snug text-primary">{listing.titleRaw ?? "Untitled"}</p>
        <p className="text-[10px] text-muted">{subtitle(listing)}</p>
        <div className="mt-auto flex items-baseline justify-between pt-1 tabular">
          <span className="text-sm font-semibold text-primary">{formatEur(listing.priceEur)}</span>
          <span className="text-[10px] text-muted">{listing.mileageKm !== null ? formatKm(listing.mileageKm) : "—"}</span>
        </div>
      </div>
    </a>
  );
}

function ListingRow({
  listing,
  watchlisted,
  onToggleWatchlist,
}: {
  listing: Listing;
  watchlisted: boolean;
  onToggleWatchlist: (id: string) => void;
}) {
  return (
    <a
      href={listing.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 rounded-md border border-border bg-surface-1 p-2 hover:border-series-1/50"
    >
      <div className="h-14 w-20 shrink-0 overflow-hidden rounded bg-surface-2">
        {listing.photoUrls[0] && (
          <img
            src={listing.photoUrls[0]}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-primary">{listing.titleRaw ?? "Untitled"}</p>
        <p className="text-[10px] text-muted">
          {SOURCE_LABELS[listing.source] ?? listing.source} · {COUNTRY_FLAGS[listing.country] ?? listing.country} ·{" "}
          {subtitle(listing)}
        </p>
      </div>
      {listing.isNew && (
        <span className="shrink-0 rounded bg-status-warning px-1.5 py-0.5 text-[10px] font-semibold text-black">NEW</span>
      )}
      <div className="shrink-0 text-right tabular">
        <div className="text-sm font-semibold text-primary">{formatEur(listing.priceEur)}</div>
        <div className="text-[10px] text-muted">{listing.mileageKm !== null ? formatKm(listing.mileageKm) : "—"}</div>
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          onToggleWatchlist(listing.id);
        }}
        className="shrink-0 text-sm"
      >
        {watchlisted ? "★" : "☆"}
      </button>
    </a>
  );
}
