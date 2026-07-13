import { describe, expect, it } from "vitest";

import type {
  StockSearchItem,
  WatchlistItemWithQuote,
} from "@/core/market/types";
import {
  optimisticWatchlistItem,
  withOptimisticWatchlistItem,
} from "@/core/market/watchlist-cache";

function stock(overrides: Partial<StockSearchItem> = {}): StockSearchItem {
  return {
    symbol: "600519",
    name: "贵州茅台",
    market: "沪市A股",
    latest_price: 1888.0,
    change_pct: 1.2,
    turnover_rate: 0.4,
    amount: 5_000_000_000,
    float_market_cap: 2.3e12,
    total_market_cap: 2.4e12,
    concept: "白酒",
    source: "eastmoney",
    updated_at: "2026-07-10T06:30:00Z",
    ...overrides,
  };
}

function watchlistItem(
  instrument: StockSearchItem,
): WatchlistItemWithQuote {
  return {
    id: `existing:${instrument.market}:${instrument.symbol}`,
    instrument,
    sort_order: 0,
    note: "",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    quote: null,
  };
}

describe("optimisticWatchlistItem", () => {
  it("carries the search result's day-level stats so the row renders numbers instantly", () => {
    const item = optimisticWatchlistItem(stock());
    expect(item.instrument.latest_price).toBe(1888.0);
    expect(item.instrument.change_pct).toBe(1.2);
    expect(item.quote).toBeNull();
    expect(item.id).toBe("optimistic:沪市A股:600519");
  });
});

describe("withOptimisticWatchlistItem", () => {
  it("prepends the new stock to the cached list", () => {
    const existing = watchlistItem(stock({ symbol: "000858", name: "五粮液" }));
    const next = withOptimisticWatchlistItem([existing], stock());
    expect(next?.map((item) => item.instrument.symbol)).toEqual([
      "600519",
      "000858",
    ]);
  });

  it("does not duplicate a stock that is already in the list", () => {
    const existing = watchlistItem(stock());
    const next = withOptimisticWatchlistItem([existing], stock());
    expect(next).toHaveLength(1);
    expect(next?.[0]?.id).toBe(existing.id);
  });

  it("matches identity on trimmed market:symbol", () => {
    const existing = watchlistItem(stock({ market: " 沪市A股 ", symbol: " 600519 " }));
    const next = withOptimisticWatchlistItem([existing], stock());
    expect(next).toHaveLength(1);
  });

  it("leaves an unpopulated cache entry untouched", () => {
    expect(withOptimisticWatchlistItem(undefined, stock())).toBeUndefined();
  });
});
