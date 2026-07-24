import { describe, expect, it } from "vitest";

import {
  formatIntradayTime,
  intradayTime,
  movingAverage,
} from "@/components/workspace/market/chart-theme";
import type { IntradayPoint, KlineBar } from "@/core/market/types";

function bar(date: string, close: number): KlineBar {
  return { date, open: close, high: close, low: close, close, volume: 0 };
}

function point(time: string): IntradayPoint {
  return { time, price: 10, avg_price: 10 };
}

describe("movingAverage", () => {
  it("averages a trailing window and skips bars before it fills", () => {
    const bars = [1, 2, 3, 4, 5].map((close, index) =>
      bar(`2026-07-0${index + 1}`, close),
    );

    expect(movingAverage(bars, 3)).toEqual([
      { time: "2026-07-03", value: 2 },
      { time: "2026-07-04", value: 3 },
      { time: "2026-07-05", value: 4 },
    ]);
  });

  it("returns nothing when there are fewer bars than the period", () => {
    expect(movingAverage([bar("2026-07-01", 10)], 5)).toEqual([]);
  });

  it("keeps the window rolling rather than accumulating every close", () => {
    // A rolling sum that forgets to drop the oldest close would drift upward.
    const bars = Array.from({ length: 30 }, (_, index) =>
      bar(`2026-07-${String(index + 1).padStart(2, "0")}`, 10),
    );

    expect(movingAverage(bars, 5).at(-1)).toEqual({
      time: "2026-07-30",
      value: 10,
    });
  });
});

describe("intradayTime", () => {
  it("round-trips a HH:MM tick back to the same label regardless of viewer timezone", () => {
    const time = intradayTime("2026-07-10", point("13:05"));

    expect(formatIntradayTime(time)).toBe("13:05");
  });

  it("keeps session minutes strictly increasing across the lunch break", () => {
    const open = intradayTime("2026-07-10", point("09:30"));
    const morningClose = intradayTime("2026-07-10", point("11:30"));
    const afternoonOpen = intradayTime("2026-07-10", point("13:00"));

    expect(open).toBeLessThan(morningClose);
    expect(morningClose).toBeLessThan(afternoonOpen);
  });

  it("falls back to the epoch when the source omits the trading day", () => {
    expect(formatIntradayTime(intradayTime("", point("09:30")))).toBe("09:30");
  });
});
