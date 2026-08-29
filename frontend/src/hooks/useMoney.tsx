import { useMemo, useState, type ReactNode } from "react";
import {
  axisWidthFor,
  formatAmount,
  formatMoney,
  formatMoneySigned,
  formatMoneyTick,
  type Currency,
} from "../lib/money";
import { MoneyContext, type Money } from "../lib/moneyContext";

const STORAGE_KEY = "car-tracker.currency";

export function MoneyProvider({ hufPerEur, children }: { hufPerEur: number | null; children: ReactNode }) {
  const [currency, setCurrency] = useState<Currency>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "EUR" || stored === "HUF") return stored;
    } catch {
      // private windows and blocked site data both throw here; the default is fine
    }
    return "HUF";
  });

  const value = useMemo<Money>(() => {
    const choose = (c: Currency) => {
      setCurrency(c);
      try {
        localStorage.setItem(STORAGE_KEY, c);
      } catch {
        // a choice that can't be remembered still applies to this visit
      }
    };
    return {
      currency,
      setCurrency: choose,
      hufPerEur,
      format: (v) => formatMoney(v, currency, hufPerEur),
      formatListingAmount: (listing, amount) =>
        listing.currencyOriginal === currency
          ? formatAmount(Math.abs(amount.original), currency)
          : formatMoney(Math.abs(amount.eur), currency, hufPerEur),
      formatListing: (listing) =>
        listing.currencyOriginal === currency && typeof listing.priceOriginal === "number"
          ? formatAmount(listing.priceOriginal, currency)
          : formatMoney(listing.priceEur, currency, hufPerEur),
      formatSigned: (v) => formatMoneySigned(v, currency, hufPerEur),
      formatTick: (v) => formatMoneyTick(v, currency, hufPerEur),
      axisWidth: axisWidthFor(currency, hufPerEur),
    };
  }, [currency, hufPerEur]);

  return <MoneyContext.Provider value={value}>{children}</MoneyContext.Provider>;
}
