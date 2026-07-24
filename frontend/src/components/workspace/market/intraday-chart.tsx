"use client";

import {
  BaselineSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type MouseEventHandler,
  type Time,
} from "lightweight-charts";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { IntradaySeries } from "@/core/market/types";

import { intradayPriceSummary, type PriceChangeSummary } from "./chart-summary";
import {
  AVG_PRICE_COLOR,
  FALL_COLOR,
  PRICE_FORMAT,
  RISE_COLOR,
  baseChartOptions,
  changeColor,
  formatIntradayTime,
  intradayTime,
} from "./chart-theme";
import { EmptyChartGrid } from "./empty-chart-grid";

const INTRADAY_EMPTY_LABELS = [
  "09:30",
  "10:30",
  "11:30",
  "13:00",
  "14:00",
  "15:00",
];

type IntradayLegendValues = {
  price: number;
  avgPrice: number | null;
};

export function IntradayChart({
  series,
  onHoverSummaryChange,
}: {
  series: IntradaySeries;
  onHoverSummaryChange?: (summary: PriceChangeSummary | null) => void;
}) {
  const { t } = useI18n();
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Baseline"> | null>(null);
  const avgRef = useRef<ISeriesApi<"Line"> | null>(null);
  const prevCloseLineRef = useRef<IPriceLine | null>(null);
  const onHoverSummaryChangeRef = useRef(onHoverSummaryChange);
  const hasSeriesPoints = series.points.length > 0;
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  // Everything on this chart is drawn relative to 昨收. Without it from the
  // source, the session's own open is the only sensible baseline.
  const prevClose = series.prev_close ?? series.points[0]?.price ?? 0;
  const prevCloseLabel = t.market.prevClose;

  const { pricePoints, avgPoints } = useMemo(() => {
    const prices = series.points.map((point) => ({
      time: intradayTime(series.date, point),
      value: point.price,
    }));
    const averages = series.points
      .filter((point) => point.avg_price !== null)
      .map((point) => ({
        time: intradayTime(series.date, point),
        value: point.avg_price!,
      }));
    return { pricePoints: prices, avgPoints: averages };
  }, [series.date, series.points]);
  const hoverSummaries = useMemo(() => {
    const summaries = new Map<number, PriceChangeSummary>();
    series.points.forEach((point, index) => {
      summaries.set(
        Number(intradayTime(series.date, point)),
        intradayPriceSummary(series, index),
      );
    });
    return summaries;
  }, [series]);
  const hoverLegendValuesByTime = useMemo(() => {
    const values = new Map<number, IntradayLegendValues>();
    series.points.forEach((point) => {
      values.set(Number(intradayTime(series.date, point)), {
        price: point.price,
        avgPrice: point.avg_price,
      });
    });
    return values;
  }, [series.date, series.points]);
  const hoverSummariesRef = useRef(hoverSummaries);
  const hoverLegendValuesByTimeRef = useRef(hoverLegendValuesByTime);

  useEffect(() => {
    onHoverSummaryChangeRef.current = onHoverSummaryChange;
  }, [onHoverSummaryChange]);

  useEffect(() => {
    hoverSummariesRef.current = hoverSummaries;
  }, [hoverSummaries]);

  useEffect(() => {
    hoverLegendValuesByTimeRef.current = hoverLegendValuesByTime;
  }, [hoverLegendValuesByTime]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !hasSeriesPoints) return;

    const chart = createChart(container, {
      ...baseChartOptions(isDark),
      localization: { timeFormatter: formatIntradayTime },
      timeScale: {
        ...baseChartOptions(isDark).timeScale,
        timeVisible: true,
        tickMarkFormatter: formatIntradayTime,
      },
    });
    const price = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: prevClose },
      topLineColor: RISE_COLOR,
      topFillColor1: `${RISE_COLOR}44`,
      topFillColor2: `${RISE_COLOR}05`,
      bottomLineColor: FALL_COLOR,
      bottomFillColor1: `${FALL_COLOR}05`,
      bottomFillColor2: `${FALL_COLOR}44`,
      lineWidth: 2,
      priceFormat: PRICE_FORMAT,
    });
    const average = chart.addSeries(LineSeries, {
      color: AVG_PRICE_COLOR,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: PRICE_FORMAT,
    });

    chartRef.current = chart;
    priceRef.current = price;
    avgRef.current = average;

    const handleCrosshairMove: MouseEventHandler<Time> = (param) => {
      const handleHover = onHoverSummaryChangeRef.current;
      if (!param.point || typeof param.time !== "number") {
        setHoverTime(null);
        handleHover?.(null);
        return;
      }

      setHoverTime(param.time);
      handleHover?.(hoverSummariesRef.current.get(param.time) ?? null);
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
      priceRef.current = null;
      avgRef.current = null;
      prevCloseLineRef.current = null;
    };
  }, [hasSeriesPoints, isDark, prevClose]);

  useEffect(() => {
    const chart = chartRef.current;
    const price = priceRef.current;
    if (!chart || !price || !hasSeriesPoints) return;

    price.setData(pricePoints);
    avgRef.current?.setData(avgPoints);

    if (prevCloseLineRef.current) {
      price.removePriceLine(prevCloseLineRef.current);
      prevCloseLineRef.current = null;
    }

    prevCloseLineRef.current = price.createPriceLine({
      price: prevClose,
      color: isDark ? "#71717a" : "#94a3b8",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: prevCloseLabel,
    });

    chart.timeScale().fitContent();
  }, [
    avgPoints,
    hasSeriesPoints,
    isDark,
    prevClose,
    prevCloseLabel,
    pricePoints,
  ]);

  const lastPrice = series.points.at(-1)?.price ?? null;
  const lastAvg = avgPoints.at(-1)?.value ?? null;
  const hoverLegendValues =
    hoverTime === null
      ? null
      : (hoverLegendValuesByTime.get(hoverTime) ?? null);
  const displayPrice = hoverLegendValues?.price ?? lastPrice;
  const displayAvg =
    hoverLegendValues === null ? lastAvg : hoverLegendValues.avgPrice;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="text-muted-foreground flex items-center gap-4 px-1 text-xs tabular-nums">
        <span className="flex items-center gap-1.5">
          {t.market.prevClose}
          <span className="text-foreground font-medium">
            {prevClose ? prevClose.toFixed(2) : "--"}
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          {t.market.price}
          <span
            className="font-medium"
            style={
              typeof displayPrice === "number"
                ? { color: changeColor(displayPrice, prevClose) }
                : undefined
            }
          >
            {typeof displayPrice === "number" ? displayPrice.toFixed(2) : "--"}
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-0.5 w-3 rounded-full"
            style={{ backgroundColor: AVG_PRICE_COLOR }}
          />
          {t.market.avgPrice}
          <span className="text-foreground font-medium">
            {typeof displayAvg === "number" ? displayAvg.toFixed(2) : "--"}
          </span>
        </span>
      </div>
      {hasSeriesPoints ? (
        <div ref={containerRef} className="min-h-0 flex-1" />
      ) : (
        <div className="min-h-0 flex-1">
          <EmptyChartGrid xLabels={INTRADAY_EMPTY_LABELS} />
        </div>
      )}
    </div>
  );
}
