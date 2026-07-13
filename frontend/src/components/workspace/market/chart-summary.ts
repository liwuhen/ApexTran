import type { IntradaySeries, KlineBar } from "@/core/market/types";

export type PriceChangeSummary = {
  price: number | null;
  changePct: number | null;
};

export function dailyPriceSummary(
  bars: KlineBar[],
  index = bars.length - 1,
): PriceChangeSummary {
  const current = bars[index];
  const previous = bars[index - 1];

  return {
    price: current?.close ?? null,
    changePct: calculateChangePct(current?.close, previous?.close),
  };
}

export function intradayPriceSummary(
  series: IntradaySeries,
  index = series.points.length - 1,
): PriceChangeSummary {
  const current = series.points[index];

  return {
    price: current?.price ?? null,
    changePct: calculateChangePct(current?.price, series.prev_close),
  };
}

export function calculateChangePct(
  value: number | null | undefined,
  baseline: number | null | undefined,
) {
  if (typeof value !== "number" || typeof baseline !== "number") return null;
  if (baseline === 0) return null;
  return ((value - baseline) / baseline) * 100;
}
