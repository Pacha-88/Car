import { useEffect, useState } from "react";
import type { ExportPayload, Listing, MarketDay, SaleTime } from "../types";

interface ListingsState {
  listings: Listing[];
  generatedAt: string | null;
  latestScrapeDate: string | null;
  /** The scrape's exact moment, UTC-marked; null on an older export. */
  latestScrapeAt: string | null;
  hufPerEur: number | null;
  /** One row per day per model, oldest first. Empty until a run has
   * written one - an export from before this field existed has none. */
  marketHistory: MarketDay[];
  /** Median witnessed days-to-sale per model/variant; empty until enough
   * watched cars have sold. */
  saleTimes: SaleTime[];
  loading: boolean;
  error: string | null;
}

const INITIAL_STATE: ListingsState = {
  listings: [],
  generatedAt: null,
  latestScrapeDate: null,
  latestScrapeAt: null,
  hufPerEur: null,
  marketHistory: [],
  saleTimes: [],
  loading: true,
  error: null,
};

/** Reads the static export `car-tracker export` produces - a stand-in for
 * a live Supabase query, same listing shape either way (see backend
 * README). Swapping this hook's body for a Supabase client call is the
 * only change needed to go live. */
export function useListings(): ListingsState {
  const [state, setState] = useState<ListingsState>(INITIAL_STATE);

  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}data/listings.json`)
      .then((res) => {
        if (!res.ok) throw new Error(`failed to load listings.json (HTTP ${res.status})`);
        return res.json() as Promise<ExportPayload>;
      })
      .then((payload) => {
        if (cancelled) return;
        setState({
          // The payload is a file on a web server, not a value this app
          // produced: a row stored before the source hardening carries
          // photoUrls: null, and `listing.photoUrls[0]` on that throws and
          // takes the whole grid down. Normalised once, here, rather than
          // optional-chained at each of the four places that read it.
          listings: (payload.listings ?? []).map((l) => ({
            ...l,
            photoUrls: Array.isArray(l.photoUrls) ? l.photoUrls.filter((u) => typeof u === "string") : [],
          })),
          generatedAt: payload.generatedAt,
          latestScrapeDate: payload.latestScrapeDate,
          latestScrapeAt: payload.latestScrapeAt ?? null,
          // An export written before this field existed simply has no rate.
          hufPerEur: payload.hufPerEur ?? null,
          marketHistory: payload.marketHistory ?? [],
          saleTimes: payload.saleTimes ?? [],
          loading: false,
          error: null,
        });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setState((s) => ({ ...s, loading: false, error: err.message }));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
