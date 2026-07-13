"use client";

import { TriangleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { useDailyKline, useIntraday } from "@/core/market/hooks";
import type { IntradaySeries, KlineBar } from "@/core/market/types";

import {
  dailyPriceSummary,
  intradayPriceSummary,
  type PriceChangeSummary,
} from "./chart-summary";
import { FALL_COLOR, RISE_COLOR } from "./chart-theme";
import { DailyKlineChart } from "./daily-kline-chart";
import { IntradayChart } from "./intraday-chart";

type ChartTab = "daily" | "intraday";

const CHART_CONTENT_CLASS = "h-[420px] flex-none";

export type ChartedStock = {
  symbol: string;
  name: string;
  market?: string;
};

export type StockChartDialogController = {
  stock: ChartedStock | null;
  isOpen: boolean;
  open: (stock: ChartedStock) => void;
  close: () => void;
  onOpenChange: (open: boolean) => void;
};

export function useStockChartDialog(): StockChartDialogController {
  const [stock, setStock] = useState<ChartedStock | null>(null);
  const open = useCallback((nextStock: ChartedStock) => {
    setStock(nextStock);
  }, []);
  const close = useCallback(() => {
    setStock(null);
  }, []);
  const onOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        close();
      }
    },
    [close],
  );

  return useMemo(
    () => ({
      stock,
      isOpen: stock !== null,
      open,
      close,
      onOpenChange,
    }),
    [close, onOpenChange, open, stock],
  );
}

export function StockChartDialogHost({
  controller,
}: {
  controller: StockChartDialogController;
}) {
  return (
    <StockChartDialog
      stock={controller.stock}
      onOpenChange={controller.onOpenChange}
    />
  );
}

export function StockChartDialog({
  stock,
  onOpenChange,
}: {
  stock: ChartedStock | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={stock !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        {stock ? <StockCharts stock={stock} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function StockCharts({ stock }: { stock: ChartedStock }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<ChartTab>("daily");
  const [dailyHoverSummary, setDailyHoverSummary] =
    useState<PriceChangeSummary | null>(null);
  const [intradayHoverSummary, setIntradayHoverSummary] =
    useState<PriceChangeSummary | null>(null);
  // Each tab fetches only while it is the visible one, so opening the dialog
  // never starts two polls at once.
  const kline = useDailyKline({
    symbol: stock.symbol,
    market: stock.market,
    enabled: tab === "daily",
  });
  const intraday = useIntraday({
    symbol: stock.symbol,
    market: stock.market,
    enabled: tab === "intraday",
  });
  const emptyIntradaySeries = useMemo<IntradaySeries>(
    () => ({
      symbol: stock.symbol,
      date: "",
      prev_close: null,
      points: [],
      updated_at: "",
    }),
    [stock.symbol],
  );
  const intradaySeries = intraday.series ?? emptyIntradaySeries;
  const hoverSummary =
    tab === "daily" ? dailyHoverSummary : intradayHoverSummary;

  useEffect(() => {
    setDailyHoverSummary(null);
    setIntradayHoverSummary(null);
  }, [stock.symbol]);

  const handleTabChange = (value: string) => {
    setTab(value as ChartTab);
    setDailyHoverSummary(null);
    setIntradayHoverSummary(null);
  };

  return (
    <Tabs value={tab} onValueChange={handleTabChange}>
      <DialogHeader className="gap-3 text-left">
        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 pr-8">
          <DialogTitle className="flex min-w-0 items-baseline gap-2">
            <span className="truncate">{stock.name}</span>
            <span className="text-muted-foreground shrink-0 text-sm font-normal tabular-nums">
              {stock.symbol}
            </span>
          </DialogTitle>
          <TabsList className="justify-self-center">
            <TabsTrigger value="daily">{t.market.dailyKline}</TabsTrigger>
            <TabsTrigger value="intraday">{t.market.intradayChart}</TabsTrigger>
          </TabsList>
          <span aria-hidden="true" className="min-w-0" />
        </div>

        <DialogDescription className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <ChartSummary
            tab={tab}
            bars={kline.bars}
            series={intradaySeries}
            hoverSummary={hoverSummary}
          />
        </DialogDescription>
      </DialogHeader>

      <TabsContent value="daily" className={CHART_CONTENT_CLASS}>
        <ChartPanel
          isLoading={kline.isLoading}
          error={kline.error}
          isRetrying={kline.isFetching}
          onRetry={() => void kline.refetch()}
        >
          <DailyKlineChart
            key={stock.symbol}
            bars={kline.bars}
            onHoverSummaryChange={setDailyHoverSummary}
          />
        </ChartPanel>
      </TabsContent>

      <TabsContent value="intraday" className={CHART_CONTENT_CLASS}>
        <ChartPanel
          isLoading={intraday.isLoading}
          error={intraday.error}
          isRetrying={intraday.isFetching}
          onRetry={() => void intraday.refetch()}
        >
          <IntradayChart
            key={stock.symbol}
            series={intradaySeries}
            onHoverSummaryChange={setIntradayHoverSummary}
          />
        </ChartPanel>
      </TabsContent>
    </Tabs>
  );
}

function ChartSummary({
  tab,
  bars,
  series,
  hoverSummary,
}: {
  tab: ChartTab;
  bars: KlineBar[];
  series: IntradaySeries;
  hoverSummary: PriceChangeSummary | null;
}) {
  const { t } = useI18n();
  const summary =
    hoverSummary ??
    (tab === "daily" ? dailyPriceSummary(bars) : intradayPriceSummary(series));
  const priceLabel =
    tab === "daily" ? t.market.closePrice : t.market.currentPrice;
  const changeLabel =
    tab === "daily" ? t.market.closeChangePct : t.market.currentChangePct;
  const valueStyle =
    summary.changePct === null
      ? undefined
      : { color: summary.changePct >= 0 ? RISE_COLOR : FALL_COLOR };

  return (
    <>
      <span className="inline-flex items-center gap-1.5">
        {priceLabel}
        <span className="text-foreground font-medium tabular-nums">
          {formatPrice(summary.price)}
        </span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        {changeLabel}
        <span className="font-medium tabular-nums" style={valueStyle}>
          {formatChangePct(summary.changePct)}
        </span>
      </span>
    </>
  );
}

function formatPrice(value: number | null) {
  return typeof value === "number" ? value.toFixed(2) : "--";
}

function formatChangePct(value: number | null) {
  if (typeof value !== "number") return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function ChartPanel({
  isLoading,
  error,
  isRetrying,
  onRetry,
  children,
}: {
  isLoading: boolean;
  error: Error | null;
  isRetrying: boolean;
  onRetry: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();

  if (error) {
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>{t.market.loadFailed}</AlertTitle>
          <AlertDescription>
            <Button
              variant="outline"
              size="sm"
              onClick={onRetry}
              disabled={isRetrying}
              className="mt-3"
            >
              {t.market.retry}
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-full flex-col gap-2 p-1">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="min-h-0 flex-1" />
      </div>
    );
  }

  return <>{children}</>;
}
