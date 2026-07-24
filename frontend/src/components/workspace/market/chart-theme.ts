import {
  ColorType,
  CrosshairMode,
  LineStyle,
  type ChartOptions,
  type DeepPartial,
  type LineData,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { IntradayPoint, KlineBar } from "@/core/market/types";

// A-share convention: 红涨绿跌 — the inverse of Western markets.
export const RISE_COLOR = "#ef4444";
export const FALL_COLOR = "#10b981";
export const AVG_PRICE_COLOR = "#f59e0b";
export const MA_COLORS = ["#f59e0b", "#3b82f6", "#a855f7"] as const;
export const MA_PERIODS = [5, 10, 20] as const;

export const PRICE_FORMAT = {
  type: "price",
  precision: 2,
  minMove: 0.01,
} as const;

export function baseChartOptions(isDark: boolean): DeepPartial<ChartOptions> {
  const gridColor = isDark ? "#27272a" : "#f1f5f9";
  const textColor = isDark ? "#a1a1aa" : "#64748b";
  const borderColor = isDark ? "#3f3f46" : "#e2e8f0";

  return {
    autoSize: true,
    layout: {
      // Transparent so the dialog's own background (and its theme) shows through.
      background: { type: ColorType.Solid, color: "transparent" },
      textColor,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: gridColor },
      horzLines: { color: gridColor },
    },
    rightPriceScale: { borderColor },
    timeScale: { borderColor },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: textColor, style: LineStyle.Dashed, width: 1 },
      horzLine: { color: textColor, style: LineStyle.Dashed, width: 1 },
    },
  };
}

/** Rolling simple moving average over closes. Bars before the window fills are omitted. */
export function movingAverage(bars: KlineBar[], period: number): LineData[] {
  const points: LineData[] = [];
  let sum = 0;

  for (let index = 0; index < bars.length; index++) {
    const bar = bars[index];
    if (!bar) continue;
    sum += bar.close;

    const dropped = bars[index - period];
    if (dropped) sum -= dropped.close;

    if (index >= period - 1) {
      points.push({ time: bar.date, value: Number((sum / period).toFixed(3)) });
    }
  }

  return points;
}

/**
 * Minute ticks carry no date, and the chart needs strictly increasing times.
 * Anchor each `HH:MM` to its trading day at UTC — the axis is index-based, so the
 * zone only has to be consistent, and the formatters below read it back as UTC.
 */
export function intradayTime(date: string, point: IntradayPoint): UTCTimestamp {
  const day = date || "1970-01-01";
  return (Date.parse(`${day}T${point.time}:00Z`) / 1000) as UTCTimestamp;
}

/** Renders an `intradayTime` value back as the exchange-local `HH:MM` it came from. */
export function formatIntradayTime(time: Time): string {
  const date = new Date((time as UTCTimestamp) * 1000);
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

export function changeColor(value: number, baseline: number): string {
  return value >= baseline ? RISE_COLOR : FALL_COLOR;
}
