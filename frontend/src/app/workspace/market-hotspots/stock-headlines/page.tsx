"use client";

import {
  CrownIcon,
  FlameIcon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  TriangleAlertIcon,
  TrendingDownIcon,
  TrendingUpIcon,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useHotlist } from "@/core/market/hooks";
import type { HotItem } from "@/core/market/types";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 15_000;
const HOTLIST_GRID_CLASS =
  "grid grid-cols-[minmax(180px,1.1fr)_112px_112px_minmax(180px,1.1fr)] items-center gap-1";

type HotlistSource = "composite" | "tonghuashun" | "eastmoney";

export default function StockHeadlinesPage() {
  const { locale, t } = useI18n();
  const [keywordInput, setKeywordInput] = useState("");
  const [activeSource, setActiveSource] = useState<HotlistSource>("composite");
  const keyword = useDeferredValue(keywordInput).trim().toLowerCase();
  const { hotlist, isLoading, isFetching, error, refetch, dataUpdatedAt } =
    useHotlist({
      refetchInterval: REFRESH_INTERVAL_MS,
    });

  useEffect(() => {
    document.title = `${t.sidebar.stockHotlist} - ${t.pages.appName}`;
  }, [t.sidebar.stockHotlist, t.pages.appName]);

  const sourceHotlist = useMemo(
    () => buildSourceHotlist(hotlist, activeSource),
    [hotlist, activeSource],
  );

  const filteredHotlist = useMemo(() => {
    if (!keyword) {
      return sourceHotlist;
    }
    return sourceHotlist.filter((item) =>
      `${item.symbol} ${item.name}`.toLowerCase().includes(keyword),
    );
  }, [sourceHotlist, keyword]);

  const stats = useMemo(() => buildStats(filteredHotlist), [filteredHotlist]);
  const leader = filteredHotlist[0] ?? null;
  const tabs = [
    { key: "tonghuashun" as const, label: t.market.tonghuashun },
    { key: "eastmoney" as const, label: t.market.eastmoney },
    { key: "composite" as const, label: t.market.compositeHotlist },
  ];

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <ScrollArea className="size-full">
          <div className="mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-6 p-6">
            <section className="relative overflow-hidden rounded-[28px] border bg-[radial-gradient(circle_at_top_left,_rgba(255,112,67,0.22),_transparent_32%),linear-gradient(135deg,_rgba(15,23,42,1),_rgba(23,37,84,0.96)_42%,_rgba(88,28,135,0.9))] p-6 text-white shadow-[0_20px_80px_rgba(15,23,42,0.3)]">
              <div className="absolute inset-0 bg-[linear-gradient(120deg,transparent,rgba(255,255,255,0.06),transparent)]" />
              <div className="relative flex flex-col gap-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="max-w-3xl">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium text-orange-200">
                      <SparklesIcon className="size-4" />
                      {t.market.autoRefreshing}
                    </div>
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h1 className="text-3xl font-semibold tracking-tight">
                        {t.market.hotlistTitle}
                      </h1>
                      <p className="max-w-xl text-sm leading-6 text-slate-200">
                        {t.market.hotlistSubtitle}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => refetch()}
                    disabled={isFetching}
                    className="border-white/15 bg-white/10 text-white hover:bg-white/16"
                  >
                    <RefreshCwIcon
                      className={cn("size-4", isFetching && "animate-spin")}
                    />
                    {t.market.refresh}
                  </Button>
                </div>

                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                  <div className="flex w-fit max-w-full flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-white/12 bg-white/10 px-4 py-3 backdrop-blur">
                    <StatItem
                      label={t.market.totalStocks}
                      value={String(filteredHotlist.length)}
                    />
                    <StatItem
                      label={t.market.topBoards}
                      value={
                        stats.maxBoards > 0
                          ? `${stats.maxBoards}${t.market.boardUnit}`
                          : "--"
                      }
                    />
                    <StatItem
                      label={t.market.strongestMove}
                      value={formatPct(stats.strongestMove)}
                      positive={stats.strongestMove >= 0}
                    />
                  </div>
                  <label className="flex items-center gap-3 rounded-2xl border border-white/12 bg-white/10 px-4 py-3 backdrop-blur">
                    <SearchIcon className="size-4 text-slate-300" />
                    <Input
                      value={keywordInput}
                      onChange={(event) => setKeywordInput(event.target.value)}
                      placeholder={t.market.searchPlaceholder}
                      aria-label={t.market.searchPlaceholder}
                      className="h-auto border-0 bg-transparent px-0 py-0 text-white shadow-none placeholder:text-slate-300 focus-visible:ring-0"
                    />
                  </label>
                </div>
              </div>
            </section>

            {/* Only surface an error when we have nothing to show. A transient
                blip during the 15s poll keeps the last snapshot on screen —
                never flash a raw "Failed to fetch" over good data. */}
            {error && hotlist.length === 0 ? (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertTitle>{t.market.loadFailed}</AlertTitle>
                <AlertDescription className="gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetch()}
                    disabled={isFetching}
                  >
                    {t.market.retry}
                  </Button>
                </AlertDescription>
              </Alert>
            ) : null}

            <section className="grid gap-4 md:grid-cols-[minmax(200px,300px)_minmax(0,1fr)]">
              <div className="space-y-4">
                <Card className="gap-4 overflow-hidden py-0">
                  <div className="bg-gradient-to-br from-amber-500/20 via-orange-500/10 to-transparent p-4">
                    <div className="mb-2 flex items-center gap-2 text-sm font-medium text-orange-600 dark:text-orange-400">
                      <CrownIcon className="size-4" />
                      NO.1
                    </div>
                    {leader ? (
                      <>
                        <div className="flex items-baseline justify-between gap-2">
                          <div className="text-xl font-semibold tracking-tight">
                            {leader.name}
                          </div>
                          <div
                            className={cn(
                              "text-lg font-semibold",
                              leader.change_pct >= 0
                                ? "text-red-500"
                                : "text-emerald-600 dark:text-emerald-400",
                            )}
                          >
                            {formatPct(leader.change_pct)}
                          </div>
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <span className="text-muted-foreground text-sm">
                            {leader.symbol}
                          </span>
                          {leader.boards > 0 && (
                            <Badge variant="secondary">
                              {leader.boards}
                              {t.market.boardUnit}
                            </Badge>
                          )}
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-1">
                          <ConceptBadges concept={leader.concept} />
                        </div>
                      </>
                    ) : (
                      <div className="space-y-2">
                        <Skeleton className="h-6 w-40" />
                        <Skeleton className="h-4 w-20" />
                        <Skeleton className="h-4 w-5/6" />
                      </div>
                    )}
                  </div>
                </Card>

                <Card className="gap-4 py-5">
                  <CardHeader className="px-5">
                    <CardTitle className="text-base">
                      {t.market.hotlistTitle}
                    </CardTitle>
                    <CardDescription>{t.market.searchHint}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4 px-5 text-sm">
                    <MetricRow
                      label={t.market.updatedAt}
                      value={formatUpdatedAt(dataUpdatedAt, locale)}
                    />
                    <MetricRow
                      label={t.market.autoRefreshing}
                      value={`${Math.floor(REFRESH_INTERVAL_MS / 1000)}s`}
                    />
                    <MetricRow
                      label={t.market.avgMove}
                      value={formatPct(stats.averageMove)}
                    />
                  </CardContent>
                </Card>
              </div>

              <Card className="gap-0 overflow-hidden py-0">
                <div className="border-b px-5 py-4">
                  <div className="mb-4 flex flex-wrap gap-2">
                    {tabs.map((tab) => (
                      <Button
                        key={tab.key}
                        variant={
                          activeSource === tab.key ? "default" : "outline"
                        }
                        size="sm"
                        onClick={() => setActiveSource(tab.key)}
                        className="rounded-full"
                      >
                        {tab.label}
                      </Button>
                    ))}
                  </div>
                  <div
                    className={cn(
                      HOTLIST_GRID_CLASS,
                      "text-muted-foreground text-xs font-medium tracking-[0.16em] uppercase",
                    )}
                  >
                    <span className="flex -translate-x-8 items-center justify-center text-center">
                      {t.market.stock}
                    </span>
                    <span className="flex -translate-x-14 items-center justify-center text-center">
                      {t.market.stockCode}
                    </span>
                    <span className="flex -translate-x-10 items-center justify-center text-center">
                      {t.market.changePct}
                    </span>
                    <span className="flex -translate-x-8 items-center justify-center text-center">
                      {t.market.concept}
                    </span>
                  </div>
                </div>
                <div className="divide-y">
                  {isLoading ? (
                    <HotlistSkeleton />
                  ) : filteredHotlist.length === 0 ? (
                    <Empty className="min-h-96 border-0">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <FlameIcon />
                        </EmptyMedia>
                        <EmptyTitle>{t.market.empty}</EmptyTitle>
                        <EmptyDescription>
                          {keywordInput || t.market.allSymbols}
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    filteredHotlist.map((item) => (
                      <HotlistRow
                        key={`${item.rank}-${item.symbol}`}
                        item={item}
                      />
                    ))
                  )}
                </div>
              </Card>
            </section>
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function StatItem({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap">
      <span className="text-sm text-slate-300">{label}</span>
      <span
        className={cn(
          "text-lg font-semibold text-white",
          positive !== undefined &&
            (positive ? "text-red-300" : "text-emerald-300"),
        )}
      >
        {value}
      </span>
    </div>
  );
}

// Concept column: each " · "-separated tag becomes a badge; 连板 tags
// ("4天3板"/"2连板"/"首板") stand out in red (A股 up = red).
function ConceptBadges({ concept }: { concept: string }) {
  if (!concept) {
    return <span className="text-muted-foreground text-sm">--</span>;
  }
  return (
    <>
      {concept.split(" · ").map((tag) => {
        const isBoard = /连板|首板|\d+天\d+板/.test(tag);
        return (
          <Badge
            key={tag}
            variant="secondary"
            className={cn(
              "font-medium",
              isBoard &&
                "bg-red-500 text-white hover:bg-red-600 dark:bg-red-600",
            )}
          >
            {tag}
          </Badge>
        );
      })}
    </>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border px-4 py-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function HotlistRow({ item }: { item: HotItem }) {
  const positive = item.change_pct >= 0;

  return (
    <div
      className={cn(
        HOTLIST_GRID_CLASS,
        "hover:bg-accent/40 px-5 py-4 text-left transition-colors",
      )}
    >
      <div className="flex min-w-0 items-center justify-start">
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-xl text-xs font-semibold",
              item.rank <= 3
                ? "bg-orange-500 text-white"
                : "bg-muted text-foreground",
            )}
          >
            {item.rank}
          </div>
          <div className="min-w-0 truncate font-semibold">{item.name}</div>
        </div>
      </div>
      <div className="-ml-7 flex items-center justify-start">
        <span className="font-medium">{item.symbol}</span>
      </div>
      <div
        className={cn(
          "-ml-7 flex items-center justify-start gap-2 font-semibold",
          positive ? "text-red-500" : "text-emerald-600 dark:text-emerald-400",
        )}
      >
        {positive ? (
          <TrendingUpIcon className="size-4" />
        ) : (
          <TrendingDownIcon className="size-4" />
        )}
        {formatPct(item.change_pct)}
      </div>
      <div className="flex flex-wrap items-center justify-start gap-1">
        <ConceptBadges concept={item.concept} />
      </div>
    </div>
  );
}

function HotlistSkeleton() {
  return (
    <>
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className={cn(HOTLIST_GRID_CLASS, "px-5 py-4")}>
          <div className="flex justify-start">
            <Skeleton className="h-5 w-32" />
          </div>
          <div className="flex justify-start">
            <Skeleton className="h-5 w-14" />
          </div>
          <div className="flex justify-start">
            <Skeleton className="h-5 w-20" />
          </div>
          <div className="flex justify-start">
            <div className="w-full max-w-md space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

function buildStats(items: HotItem[]) {
  if (items.length === 0) {
    return {
      maxBoards: 0,
      strongestMove: 0,
      averageMove: 0,
    };
  }

  const strongestMove = Math.max(...items.map((item) => item.change_pct));
  const maxBoards = Math.max(...items.map((item) => item.boards));
  const averageMove =
    items.reduce((sum, item) => sum + item.change_pct, 0) / items.length;

  return {
    maxBoards,
    strongestMove,
    averageMove,
  };
}

function buildSourceHotlist(items: HotItem[], source: HotlistSource) {
  if (source === "composite") {
    return items;
  }

  const getSourceRank = (item: HotItem) =>
    source === "tonghuashun" ? item.tonghuashun_rank : item.eastmoney_rank;

  return items
    .filter((item) => getSourceRank(item) !== null)
    .sort((a, b) => {
      const rankA = getSourceRank(a);
      const rankB = getSourceRank(b);
      if (rankA === null && rankB === null) {
        return a.rank - b.rank;
      }
      if (rankA === null) {
        return 1;
      }
      if (rankB === null) {
        return -1;
      }
      return rankA - rankB;
    })
    .map((item, index) => ({
      ...item,
      rank: index + 1,
    }));
}

function formatPct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatUpdatedAt(timestamp: number, locale: string) {
  if (!timestamp) {
    return "--";
  }
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return new Intl.DateTimeFormat(locale, {
    timeZone: "Asia/Shanghai",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
