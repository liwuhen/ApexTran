import { afterEach, describe, expect, it, vi } from "vitest";

import { loadDailyKlines } from "@/core/market/api";
import { marketRef, marketRefKey } from "@/core/market/refs";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// The market API always calls fetch with a string URL, so the stub types it as
// one — that keeps the request assertions below free of stringification casts.
function stubFetch(body: unknown) {
  const fetchMock = vi.fn(async (_url: string) => ({
    ok: true,
    status: 200,
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("market refs", () => {
  it("keys a stock by market and symbol, tolerating whitespace", () => {
    expect(marketRefKey({ market: " 沪市A股 ", symbol: "600519 " })).toBe(
      "沪市A股:600519",
    );
  });

  it("omits the market prefix on the wire when there is no market", () => {
    expect(marketRef({ symbol: "600519" })).toBe("600519");
    expect(marketRef({ market: "沪市A股", symbol: "600519" })).toBe(
      "沪市A股:600519",
    );
  });
});

describe("loadDailyKlines", () => {
  it("asks for the whole watchlist in a single request", async () => {
    const fetchMock = stubFetch([
      { market: "沪市A股", symbol: "600519", bars: [] },
      { market: "深市A股", symbol: "000060", bars: [] },
    ]);

    await loadDailyKlines(
      [
        { market: "沪市A股", symbol: "600519" },
        { market: "深市A股", symbol: "000060" },
      ],
      120,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0]![0];
    expect(url).toContain("/api/v1/market/klines?");
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("symbols")).toBe("沪市A股:600519,深市A股:000060");
    expect(params.get("limit")).toBe("120");
  });

  it("does not call the backend for an empty watchlist", async () => {
    const fetchMock = stubFetch([]);

    expect(await loadDailyKlines([])).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns each symbol's bars as sent by the backend", async () => {
    stubFetch([
      {
        market: "沪市A股",
        symbol: "600519",
        bars: [
          {
            date: "2026-07-13",
            open: 1680,
            high: 1700,
            low: 1675,
            close: 1688,
            volume: 12_000,
          },
        ],
      },
    ]);

    const [series] = await loadDailyKlines([
      { market: "沪市A股", symbol: "600519" },
    ]);

    expect(marketRefKey(series!)).toBe("沪市A股:600519");
    expect(series!.bars).toHaveLength(1);
    expect(series!.bars[0]?.close).toBe(1688);
  });
});
