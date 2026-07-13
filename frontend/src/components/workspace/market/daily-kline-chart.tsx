"use client";

import {
  CandlestickSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventHandler,
  type Time,
} from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";

import type { KlineBar } from "@/core/market/types";

import { dailyPriceSummary, type PriceChangeSummary } from "./chart-summary";
import {
  FALL_COLOR,
  MA_COLORS,
  MA_PERIODS,
  PRICE_FORMAT,
  RISE_COLOR,
  baseChartOptions,
  movingAverage,
} from "./chart-theme";
import { EmptyChartGrid } from "./empty-chart-grid";

export function DailyKlineChart({
  bars,
  onHoverSummaryChange,
}: {
  bars: KlineBar[];
  onHoverSummaryChange?: (summary: PriceChangeSummary | null) => void;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const hasBars = bars.length > 0;
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const maRefs = useRef<ISeriesApi<"Line">[]>([]);
  const onHoverSummaryChangeRef = useRef(onHoverSummaryChange);
  const [hoverDate, setHoverDate] = useState<string | null>(null);

  const movingAverages = useMemo(
    () => MA_PERIODS.map((period) => movingAverage(bars, period)),
    [bars],
  );
  const movingAverageValueMaps = useMemo(
    () =>
      movingAverages.map(
        (points) =>
          new Map(
            points.flatMap((point) =>
              typeof point.time === "string" ? [[point.time, point.value]] : [],
            ),
          ),
      ),
    [movingAverages],
  );
  const hoverSummaries = useMemo(() => {
    const summaries = new Map<string, PriceChangeSummary>();
    bars.forEach((bar, index) => {
      summaries.set(bar.date, dailyPriceSummary(bars, index));
    });
    return summaries;
  }, [bars]);
  const hoverSummariesRef = useRef(hoverSummaries);

  useEffect(() => {
    onHoverSummaryChangeRef.current = onHoverSummaryChange;
  }, [onHoverSummaryChange]);

  useEffect(() => {
    hoverSummariesRef.current = hoverSummaries;
  }, [hoverSummaries]);

  const legendHoverDate =
    hoverDate !== null && hoverSummaries.has(hoverDate) ? hoverDate : null;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !hasBars) return;

    const chart = createChart(container, baseChartOptions(isDark));
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: RISE_COLOR,
      downColor: FALL_COLOR,
      borderUpColor: RISE_COLOR,
      borderDownColor: FALL_COLOR,
      wickUpColor: RISE_COLOR,
      wickDownColor: FALL_COLOR,
      priceFormat: PRICE_FORMAT,
    });
    const averages = MA_COLORS.map((color) =>
      chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat: PRICE_FORMAT,
      }),
    );

    chartRef.current = chart;
    candlesRef.current = candles;
    maRefs.current = averages;

    const handleCrosshairMove: MouseEventHandler<Time> = (param) => {
      const handleHover = onHoverSummaryChangeRef.current;
      if (!param.point || typeof param.time !== "string") {
        setHoverDate(null);
        handleHover?.(null);
        return;
      }

      setHoverDate(param.time);
      handleHover?.(hoverSummariesRef.current.get(param.time) ?? null);
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
      candlesRef.current = null;
      maRefs.current = [];
    };
  }, [hasBars, isDark]);

  useEffect(() => {
    const chart = chartRef.current;
    const candles = candlesRef.current;
    if (!chart || !candles || !hasBars) return;

    candles.setData(
      bars.map((bar) => ({
        time: bar.date,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    movingAverages.forEach((points, index) =>
      maRefs.current[index]?.setData(points),
    );
    chart.timeScale().fitContent();
    // `isDark` rebuilds the chart and its series above; re-feed the new ones.
  }, [bars, hasBars, isDark, movingAverages]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <MovingAverageLegend
        movingAverages={movingAverages}
        movingAverageValueMaps={movingAverageValueMaps}
        hoverDate={legendHoverDate}
      />
      {hasBars ? (
        <div ref={containerRef} className="min-h-0 flex-1" />
      ) : (
        <div className="min-h-0 flex-1">
          <EmptyChartGrid />
        </div>
      )}
    </div>
  );
}

function MovingAverageLegend({
  movingAverages,
  movingAverageValueMaps,
  hoverDate,
}: {
  movingAverages: ReturnType<typeof movingAverage>[];
  movingAverageValueMaps: Map<string, number>[];
  hoverDate: string | null;
}) {
  return (
    <div className="text-muted-foreground flex items-center gap-4 px-1 text-xs tabular-nums">
      {MA_PERIODS.map((period, index) => {
        const points = movingAverages[index] ?? [];
        const value =
          hoverDate !== null
            ? movingAverageValueMaps[index]?.get(hoverDate)
            : points.at(-1)?.value;
        return (
          <span key={period} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-0.5 w-3 rounded-full"
              style={{ backgroundColor: MA_COLORS[index] }}
            />
            MA{period}
            <span className="text-foreground font-medium">
              {typeof value === "number" ? value.toFixed(2) : "--"}
            </span>
          </span>
        );
      })}
    </div>
  );
}
