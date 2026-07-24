"use client";

import { RadioIcon, RefreshCwIcon, SparklesIcon, ZapIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useAiHotspots, useFlash } from "@/core/market/hooks";
import type { FlashItem, NewsItem } from "@/core/market/types";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 15_000;
const MAX_FLASH_ITEMS = 60;
const MAX_AI_HOTSPOTS = 60;

type FlashTab = "ai" | "cls" | "wallstreetcn";

export default function FlashNewsPage() {
  const { locale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<FlashTab>("ai");
  const {
    flash,
    isLoading: isFlashLoading,
    isFetching: isFlashFetching,
    refetch: refetchFlash,
  } = useFlash({
    refetchInterval: REFRESH_INTERVAL_MS,
  });
  const {
    aiHotspots,
    isLoading: isAiLoading,
    isFetching: isAiFetching,
    refetch: refetchAiHotspots,
  } = useAiHotspots({
    refetchInterval: REFRESH_INTERVAL_MS,
  });

  useEffect(() => {
    document.title = `${t.sidebar.flashNews} - ${t.pages.appName}`;
  }, [t.sidebar.flashNews, t.pages.appName]);

  const tabs = [
    { key: "ai" as const, label: t.market.aiAggregation },
    { key: "cls" as const, label: t.market.cls },
    { key: "wallstreetcn" as const, label: t.market.wallstreetcn },
  ];

  const tabFlash = useMemo(
    () => buildTabFlash(flash, activeTab),
    [flash, activeTab],
  );
  const visibleAiHotspots = useMemo(
    () => dedupeNewsById(aiHotspots).slice(0, MAX_AI_HOTSPOTS),
    [aiHotspots],
  );
  const isLoading = activeTab === "ai" ? isAiLoading : isFlashLoading;
  const isFetching = isAiFetching || isFlashFetching;
  const currentItemsLength = activeTab === "ai" ? visibleAiHotspots.length : tabFlash.length;
  const refetchActiveTab = () => {
    if (activeTab === "ai") {
      void refetchAiHotspots();
      return;
    }
    void refetchFlash();
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <ScrollArea className="size-full">
          <div className="mx-auto flex w-full max-w-(--container-width-lg) flex-col gap-6 p-6">
            <section className="relative overflow-hidden rounded-[28px] border bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.22),_transparent_28%),linear-gradient(135deg,_rgba(7,89,133,1),_rgba(17,24,39,0.96)_45%,_rgba(6,78,59,0.92))] p-6 text-white shadow-[0_20px_80px_rgba(15,23,42,0.24)]">
              <div className="absolute inset-0 bg-[linear-gradient(120deg,transparent,rgba(255,255,255,0.06),transparent)]" />
              <div className="relative flex flex-col gap-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="max-w-3xl">
                    <div className="mb-3 flex items-center gap-2 text-sm font-medium text-amber-100">
                      <SparklesIcon className="size-4" />
                      {t.market.autoRefreshing}
                    </div>
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <h1 className="text-3xl font-semibold tracking-tight">
                        {t.market.flashNewsTitle}
                      </h1>
                      <p className="max-w-xl text-sm leading-6 text-slate-100/90">
                        {t.market.flashNewsSubtitle}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    onClick={refetchActiveTab}
                    disabled={isFetching}
                    className="border-white/15 bg-white/10 text-white hover:bg-white/16"
                  >
                    <RefreshCwIcon
                      className={cn("size-4", isFetching && "animate-spin")}
                    />
                    {t.market.refresh}
                  </Button>
                </div>
              </div>
            </section>

            <section>
              <Card className="overflow-hidden py-0">
                <CardHeader className="border-b px-5 py-5">
                  <div className="flex flex-col gap-4">
                    <div>
                      <CardTitle className="flex items-center gap-2 text-lg">
                        <RadioIcon className="size-5 text-amber-500" />
                        {t.market.flashHeading}
                      </CardTitle>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {tabs.map((tab) => (
                        <Button
                          key={tab.key}
                          variant={activeTab === tab.key ? "default" : "outline"}
                          size="sm"
                          onClick={() => setActiveTab(tab.key)}
                          className="rounded-full"
                        >
                          {tab.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="px-0 py-0">
                  {isLoading ? (
                    <FlashListSkeleton />
                  ) : currentItemsLength === 0 ? (
                    <Empty className="min-h-96 border-0">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <ZapIcon />
                        </EmptyMedia>
                        <EmptyTitle>{t.market.noFlash}</EmptyTitle>
                        <EmptyDescription>
                          {tabs.find((tab) => tab.key === activeTab)?.label}
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : activeTab === "ai" ? (
                    <div className="divide-y">
                      {visibleAiHotspots.map((item, index) => (
                        <AiHotspotRow
                          key={item.id}
                          item={item}
                          index={index + 1}
                          locale={locale}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="divide-y">
                      {tabFlash.map((item) => (
                        <FlashRow key={item.id} item={item} locale={locale} />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </section>
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function AiHotspotRow({
  item,
  index,
  locale,
}: {
  item: NewsItem;
  index: number;
  locale: string;
}) {
  const href = item.url.trim() || "https://stock.quicktiny.cn/news-hotlist";
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={item.summary ? `${item.title}\n${item.summary}` : item.title}
      className="group grid gap-3 px-5 py-4 transition-colors hover:bg-accent/40 sm:grid-cols-[64px_minmax(0,1fr)]"
    >
      <div className="flex items-start">
        <div className="bg-muted text-muted-foreground flex size-8 items-center justify-center rounded-lg text-xs font-semibold">
          {index}
        </div>
      </div>
      <div className="min-w-0">
        <div className="line-clamp-2 break-words font-semibold leading-6 group-hover:text-emerald-600 dark:group-hover:text-emerald-400">
          {item.title}
        </div>
        <p className="text-muted-foreground mt-2 line-clamp-3 break-words text-sm leading-6">
          {item.summary || "--"}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{item.source || "AI智能热榜"}</Badge>
          {item.heat !== null ? (
            <Badge variant="outline">热度 {formatCompactNumber(item.heat)}</Badge>
          ) : null}
          {item.views !== null ? (
            <Badge variant="outline">综合分 {formatCompactNumber(item.views)}</Badge>
          ) : null}
          {item.tags.slice(0, 4).map((tag) => (
            <Badge key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
          <span className="text-muted-foreground text-sm">
            {formatNewsTime(item.published_at, locale)}
          </span>
        </div>
      </div>
    </a>
  );
}

function FlashRow({ item, locale }: { item: FlashItem; locale: string }) {
  const isImportant = item.level === "important";
  const href = item.url.trim() || "#";
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={item.title ? `${item.title}\n${item.content}` : item.content}
      className="group grid gap-3 px-5 py-4 transition-colors hover:bg-accent/40 sm:grid-cols-[64px_minmax(0,1fr)]"
    >
      <div className="text-muted-foreground flex items-start gap-2 text-sm font-medium tabular-nums">
        <span
          className={cn(
            "mt-[7px] size-2 shrink-0 rounded-full",
            isImportant ? "bg-red-500" : "bg-muted-foreground/30",
          )}
        />
        {formatFlashTime(item.published_at, locale)}
      </div>
      <div className="min-w-0">
        {item.title ? (
          <div className="mb-1 line-clamp-2 break-words font-semibold leading-6 group-hover:text-amber-600 dark:group-hover:text-amber-400">
            {item.title}
          </div>
        ) : null}
        <p
          className={cn(
            "line-clamp-3 break-words text-sm leading-6",
            isImportant ? "text-foreground font-medium" : "text-muted-foreground",
          )}
        >
          {item.content}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Badge variant="secondary">{item.source || "--"}</Badge>
        </div>
      </div>
    </a>
  );
}

function buildTabFlash(items: FlashItem[], tab: FlashTab): FlashItem[] {
  if (tab === "ai") {
    return [];
  }
  const filtered = items.filter((item) => {
    return normalizeFlashSource(item.source) === tab;
  });
  return dedupeFlashById(filtered).slice(0, MAX_FLASH_ITEMS);
}

function normalizeFlashSource(source: string): Exclude<FlashTab, "ai"> | null {
  const normalized = source.trim().toLowerCase();
  if (normalized.includes("财联社") || normalized.includes("cls")) {
    return "cls";
  }
  if (normalized.includes("华尔街见闻") || normalized.includes("wallstreetcn")) {
    return "wallstreetcn";
  }
  return null;
}

// The list is used as a React key source, so it must not carry duplicate ids.
function dedupeFlashById(items: FlashItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

function dedupeNewsById(items: NewsItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

function formatNewsTime(timestamp: string | null, locale: string) {
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
    hour12: false,
  }).format(date);
}

function formatFlashTime(timestamp: string, locale: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return new Intl.DateTimeFormat(locale, {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatCompactNumber(value: number) {
  if (value >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1)}亿`;
  }
  if (value >= 10_000) {
    return `${(value / 10_000).toFixed(1)}万`;
  }
  return String(value);
}

function FlashListSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 8 }).map((_, index) => (
        <div
          key={index}
          className="grid gap-3 px-5 py-4 sm:grid-cols-[64px_minmax(0,1fr)]"
        >
          <Skeleton className="h-4 w-12" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-6 w-16 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}
