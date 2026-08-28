import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "car-tracker.watchlist";

function loadWatchlist(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<Set<string>>(loadWatchlist);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...watchlist]));
    } catch {
      // private browsing / storage disabled - watchlist just won't persist
    }
  }, [watchlist]);

  const toggle = useCallback((id: string) => {
    setWatchlist((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return { watchlist, toggle };
}
