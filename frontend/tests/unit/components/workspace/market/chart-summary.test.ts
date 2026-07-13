import { describe, expect, it } from "vitest";

import {
  calculateChangePct,
  dailyPriceSummary,
  intradayPriceSummary,
} from "@/components/workspace/market/chart-summary";
import type { IntradaySeries, KlineBar } from "@/core/market/types";

function bar(date: string, close: number): KlineBar {
  return { date, open: close, high: close, low: close, close, volume: 0 };
}

function intradaySeries(prevClose: number | null): IntradaySeries {
  return {
    symbol: "000001",
    date: "2026-07-10",
    prev_close: prevClose,
    points: [
      { time: "09:30", price: 10, avg_price: 10 },
      { time: "09:31", price: 10.5, avg_price: 10.25 },
    ],
    updated_at: "2026-07-10T09:31:00+08:00",
  };
}

describe("dailyPriceSummary", () => {
  it("uses the selected bar close and previous bar close for change percent", () => {
    const summary = dailyPriceSummary(
      [bar("2026-07-08", 10), bar("2026-07-09", 11)],
      1,
    );

    expect(summary.price).toBe(11);
    expect(summary.changePct).toBeCloseTo(10);
  });

  it("returns no change percent for the first visible bar", () => {
    expect(dailyPriceSummary([bar("2026-07-08", 10)], 0)).toEqual({
      price: 10,
      changePct: null,
    });
  });
});

describe("intradayPriceSummary", () => {
  it("uses the selected minute price and previous close for change percent", () => {
    const summary = intradayPriceSummary(intradaySeries(10), 1);

    expect(summary.price).toBe(10.5);
    expect(summary.changePct).toBeCloseTo(5);
  });

  it("returns no change percent when previous close is missing", () => {
    expect(intradayPriceSummary(intradaySeries(null), 1)).toEqual({
      price: 10.5,
      changePct: null,
    });
  });
});

describe("calculateChangePct", () => {
  it("does not divide by zero", () => {
    expect(calculateChangePct(10, 0)).toBeNull();
  });
});
