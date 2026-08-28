import { useEffect, useState } from "react";
import type { ExportPayload, Listing } from "../types";

interface ListingsState {
  listings: Listing[];
  generatedAt: string | null;
  latestScrapeDate: string | null;
  loading: boolean;
  error: string | null;
}

const INITIAL_STATE: ListingsState = {
  listings: [],
  generatedAt: null,
  latestScrapeDate: null,
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
          listings: payload.listings,
          generatedAt: payload.generatedAt,
          latestScrapeDate: payload.latestScrapeDate,
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
