import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loadQuotes,
  normalizeMarketStatFields,
  searchStocks,
} from "@/core/market/api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubJsonResponse(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => body,
    })),
  );
}

describe("market stat response normalization", () => {
  it("fills missing quote fields with null and preserves backend units", async () => {
    stubJsonResponse([
      {
        symbol: "600519",
        market: "沪市A股",
        latest_price: 1204.98,
        change_pct: 1.93,
        turnover_rate: 0.37,
        amount: 2_345_678_901,
        float_market_cap: null,
        source: "snapshot",
        updated_at: "2026-07-11T02:19:56Z",
      },
    ]);

    const [quote] = await loadQuotes(["沪市A股:600519"]);

    expect(quote).toMatchObject({
      turnover_rate: 0.37,
      amount: 2_345_678_901,
      float_market_cap: null,
      total_market_cap: null,
    });
  });

  it("parses finite numeric strings returned by stock search", async () => {
    stubJsonResponse([
      {
        symbol: "000001",
        name: "平安银行",
        market: "深市A股",
        latest_price: 10.45,
        change_pct: -0.38,
        turnover_rate: "1.25",
        amount: "987654321.5",
        float_market_cap: "210000000000",
        total_market_cap: "250000000000",
        concept: "银行",
        source: "snapshot",
        updated_at: "2026-07-11T02:18:17Z",
      },
    ]);

    const [stock] = await searchStocks("000001", 5);

    expect(stock).toMatchObject({
      turnover_rate: 1.25,
      amount: 987_654_321.5,
      float_market_cap: 210_000_000_000,
      total_market_cap: 250_000_000_000,
    });
  });

  it("turns empty, invalid, and non-finite values into null", () => {
    expect(
      normalizeMarketStatFields({
        turnover_rate: "",
        amount: "not-a-number",
        float_market_cap: Number.POSITIVE_INFINITY,
        total_market_cap: {},
      }),
    ).toEqual({
      turnover_rate: null,
      amount: null,
      float_market_cap: null,
      total_market_cap: null,
    });
  });
});
