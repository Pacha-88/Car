import { createContext, useContext } from "react";
import type { Currency } from "./money";

export interface Money {
  currency: Currency;
  setCurrency: (c: Currency) => void;
  /** null when no scrape has ever stored a rate — the UI then stays in euros. */
  hufPerEur: number | null;
  format: (eurValue: number) => string;
  formatSigned: (eurValue: number) => string;
  formatTick: (eurValue: number) => string;
  /** Y-axis width the current currency's ticks need. */
  axisWidth: number;
}

export const MoneyContext = createContext<Money | null>(null);

/** Currency is a display choice that reaches almost every component — stat
 * tiles, both charts, the cards, the price slider. Threading it as a prop
 * through all of them would be five signatures changed to carry one
 * setting, so it travels in context instead. */
export function useMoney(): Money {
  const value = useContext(MoneyContext);
  if (!value) throw new Error("useMoney must be used inside <MoneyProvider>");
  return value;
}
