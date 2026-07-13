// Pure cache-shaping helpers for the watchlist optimistic add flow, kept free
// of react-query so they stay unit-testable.

import type { StockSearchItem, WatchlistItemWithQuote } from "./types";

export const WATCHLIST_ITEMS_QUERY_KEY = [
  "market",
  "watchlists",
  "default",
  "items",
] as const;

// How long the backend's on-add refresh queue typically needs to land the
// realtime quote snapshot; the second invalidate fires after this delay.
export const ON_ADD_REQUOTE_DELAY_MS = 2_500;

function identity(stock: Pick<StockSearchItem, "market" | "symbol">) {
  return `${stock.market.trim()}:${stock.symbol.trim()}`;
}

// The search result already carries day-level stats from the stock pool, so the
// optimistic row renders numbers instantly; `quote` stays null until the server
// answers (the page falls back to instrument fields).
export function optimisticWatchlistItem(
  stock: StockSearchItem,
): WatchlistItemWithQuote {
  const now = new Date().toISOString();
  return {
    id: `optimistic:${identity(stock)}`,
    instrument: stock,
    sort_order: 0,
    note: "",
    created_at: now,
    updated_at: now,
    quote: null,
  };
}

export function withOptimisticWatchlistItem(
  items: WatchlistItemWithQuote[] | undefined,
  stock: StockSearchItem,
): WatchlistItemWithQuote[] | undefined {
  if (!items) {
    return items;
  }
  if (items.some((item) => identity(item.instrument) === identity(stock))) {
    return items;
  }
  return [optimisticWatchlistItem(stock), ...items];
}
