"use client";

import {
  BotIcon,
  BrainCircuitIcon,
  NewspaperIcon,
  RefreshCwIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
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
import { useNews } from "@/core/market/hooks";
import type { NewsItem } from "@/core/market/types";
import { cn } from "@/lib/utils";

const REFRESH_INTERVAL_MS = 15_000;
const AI_KEYWORDS = ["ai", "人工智能", "大模型", "算力", "芯片", "机器人", "agent"];

type FinanceSource = "cls" | "eastmoney" | "tonghuashun" | "xueqiu" | "yicai";
const MAX_SOURCE_NEWS_ITEMS = 10;

export default function SelectedNewsPage() {
  const { locale, t } = useI18n();
  const [activeSource, setActiveSource] = useState<FinanceSource>("cls");
  const { news, isLoading, isFetching, refetch } =
    useNews({
    refetchInterval: REFRESH_INTERVAL_MS,
  });

  useEffect(() => {
    document.title = `${t.sidebar.selectedNews} - ${t.pages.appName}`;
  }, [t.sidebar.selectedNews, t.pages.appName]);

  const sourceTabs = [
    { key: "cls" as const, label: t.market.cls },
    { key: "eastmoney" as const, label: t.market.eastmoney },
    { key: "tonghuashun" as const, label: t.market.tonghuashun },
    { key: "xueqiu" as const, label: t.market.xueqiu },
    { key: "yicai" as const, label: t.market.yicai },
  ];

  const sourceNewsMap = useMemo(
    () => buildSourceNewsMap(news),
    [news],
  );
  const financeNews = sourceNewsMap[activeSource];
  const aiNews = useMemo(() => buildAiHotspots(news), [news]);

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
                        {t.market.selectedNewsTitle}
                      </h1>
                      <p className="max-w-xl text-sm leading-6 text-slate-100/90">
                        {t.market.selectedNewsSubtitle}
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
              </div>
            </section>

            <section>
              <Card className="overflow-hidden py-0">
                <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
                  <div className="min-w-0">
                    <CardHeader className="border-b px-5 py-5">
                      <div className="flex flex-col gap-4">
                        <div>
                          <CardTitle className="flex items-center gap-2 text-lg">
                            <NewspaperIcon className="size-5 text-amber-500" />
                            {t.market.financialHotspots}
                          </CardTitle>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {sourceTabs.map((tab) => (
                            <Button
                              key={tab.key}
                              variant={activeSource === tab.key ? "default" : "outline"}
                              size="sm"
                              onClick={() => setActiveSource(tab.key)}
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
                        <NewsListSkeleton />
                      ) : financeNews.length === 0 ? (
                        <Empty className="min-h-96 border-0">
                          <EmptyHeader>
                            <EmptyMedia variant="icon">
                              <NewspaperIcon />
                            </EmptyMedia>
                            <EmptyTitle>{t.market.noSourceNews}</EmptyTitle>
                            <EmptyDescription>
                              {sourceTabs.find((tab) => tab.key === activeSource)?.label}
                            </EmptyDescription>
                          </EmptyHeader>
                        </Empty>
                      ) : (
                        <div className="divide-y">
                          {financeNews.map((item, index) => (
                            <NewsRow key={item.id} item={item} index={index + 1} t={t.market} locale={locale} />
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </div>

                  <div className="min-w-0">
                    <CardHeader className="border-b px-5 py-5">
                      <div className="flex flex-col gap-4">
                        <div>
                          <CardTitle className="flex items-center gap-2 text-lg">
                            <BrainCircuitIcon className="size-5 text-emerald-500" />
                            {t.market.aiHotspots}
                          </CardTitle>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button asChild variant="outline" size="sm" className="rounded-full">
                            <Link href="/workspace/market-hotspots/stock-headlines">
                              全网热点
                            </Link>
                          </Button>
                          <Button asChild variant="default" size="sm" className="rounded-full">
                            <Link href="/workspace/market-hotspots/selected-news">
                              财经资讯
                            </Link>
                          </Button>
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4 px-5 py-5">
                      {isLoading ? (
                        <AiNewsSkeleton />
                      ) : aiNews.length === 0 ? (
                        <Empty className="min-h-80 border-0">
                          <EmptyHeader>
                            <EmptyMedia variant="icon">
                              <BotIcon />
                            </EmptyMedia>
                            <EmptyTitle>{t.market.noAiNews}</EmptyTitle>
                            <EmptyDescription>{t.market.autoRefreshing}</EmptyDescription>
                          </EmptyHeader>
                        </Empty>
                      ) : (
                        aiNews.slice(0, 8).map((item) => (
                          <a
                            key={item.id}
                            href={resolveNewsUrl(item)}
                            target="_blank"
                            rel="noreferrer"
                            className="group block rounded-2xl border p-4 transition-colors hover:border-emerald-400/50 hover:bg-emerald-500/[0.04]"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <Badge variant="secondary">{normalizeSourceLabel(item.source)}</Badge>
                              <span className="text-muted-foreground text-xs">
                                {formatPublishedAt(item.published_at, locale)}
                              </span>
                            </div>
                            <div className="mt-3 line-clamp-2 font-semibold group-hover:text-emerald-600 dark:group-hover:text-emerald-400">
                              {item.title}
                            </div>
                            <p className="text-muted-foreground mt-2 line-clamp-3 text-sm leading-6">
                              {item.summary || item.tags.join(" / ") || "--"}
                            </p>
                          </a>
                        ))
                      )}
                    </CardContent>
                  </div>
                </div>
              </Card>
            </section>
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function NewsRow({
  item,
  index,
  t,
  locale,
}: {
  item: NewsItem;
  index: number;
  t: ReturnType<typeof useI18n>["t"]["market"];
  locale: string;
}) {
  const sourceKey = normalizeSourceKey(item.source);
  const showsHeatMetrics =
    sourceKey === "eastmoney" || sourceKey === "tonghuashun" || sourceKey === "yicai" || sourceKey === "xueqiu";
  const visibleTags = getVisibleNewsTags(item, sourceKey);
  const showTimestamp = sourceKey !== "tonghuashun" && item.published_at !== null;
  return (
    <a
      href={resolveNewsUrl(item)}
      target="_blank"
      rel="noreferrer"
      className="grid gap-2 px-5 py-4 transition-colors hover:bg-accent/40 lg:grid-cols-[32px_minmax(0,1fr)]"
    >
      <div className="flex items-start">
        <div className="bg-muted text-muted-foreground flex size-7 items-center justify-center rounded-lg text-xs font-semibold">
          {index}
        </div>
      </div>
      <div className="min-w-0">
        <div className="line-clamp-2 font-semibold leading-6">{item.title}</div>
        <p className="text-muted-foreground mt-2 line-clamp-3 text-sm leading-6">
          {item.summary || "--"}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {showsHeatMetrics ? (
            <>
              {item.heat !== null ? (
                <Badge variant="outline">
                  热度 {formatCompactNumber(item.heat)}
                </Badge>
              ) : null}
              {item.views !== null ? (
                <Badge variant="outline">
                  {t.views} {formatCompactNumber(item.views)}
                </Badge>
              ) : null}
              {visibleTags.slice(0, 3).map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </>
          ) : (
            visibleTags.slice(0, 4).map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))
          )}
          <Badge variant="secondary">{normalizeSourceLabel(item.source)}</Badge>
          {showTimestamp ? (
            <span className="text-muted-foreground text-sm">
              {formatPublishedAt(item.published_at, locale)}
            </span>
          ) : null}
        </div>
      </div>
    </a>
  );
}

function NewsListSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="grid gap-2 px-5 py-4 lg:grid-cols-[32px_minmax(0,1fr)]">
          <Skeleton className="mt-1 size-7 rounded-lg" />
          <div className="space-y-3">
            <Skeleton className="h-5 w-11/12" />
            <Skeleton className="h-5 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <div className="flex flex-wrap gap-2 pt-1">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-4 w-24" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function AiNewsSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="rounded-2xl border p-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-6 w-20 rounded-full" />
            <Skeleton className="h-4 w-16" />
          </div>
          <div className="mt-3 space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-5/6" />
          </div>
          <div className="mt-3 space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </div>
        </div>
      ))}
    </>
  );
}

function getVisibleNewsTags(item: NewsItem, sourceKey: FinanceSource | null) {
  const tags = item.tags.filter((tag) => tag !== "综合");
  if (sourceKey === "tonghuashun") {
    return tags.filter((tag) => tag === "精选").slice(0, 1);
  }
  return tags;
}

function buildSourceNewsMap(items: NewsItem[]) {
  const map: Record<FinanceSource, NewsItem[]> = {
    cls: [],
    eastmoney: [],
    tonghuashun: [],
    xueqiu: [],
    yicai: [],
  };

  for (const item of items) {
    const normalized = normalizeSourceKey(item.source);
    if (normalized) {
      map[normalized].push(item);
    }
  }

  for (const source of Object.keys(map) as FinanceSource[]) {
    map[source] = dedupeById(map[source]).slice(0, MAX_SOURCE_NEWS_ITEMS);
  }

  return map;
}

function buildAiHotspots(items: NewsItem[]) {
  return dedupeById(
    items.filter((item) => {
      const haystack = `${item.title} ${item.summary} ${item.tags.join(" ")}`
        .toLowerCase();
      return AI_KEYWORDS.some((keyword) => haystack.includes(keyword.toLowerCase()));
    }),
  );
}

function dedupeById(items: NewsItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

const SOURCE_HOME_URLS: Record<FinanceSource, string> = {
  cls: "https://www.cls.cn/telegraph",
  eastmoney: "https://finance.eastmoney.com/",
  tonghuashun: "https://news.10jqka.com.cn/",
  xueqiu: "https://xueqiu.com/",
  yicai: "https://www.yicai.com/",
};

function normalizeSourceKey(source: string): FinanceSource | null {
  const normalized = source.trim().toLowerCase();
  if (normalized.includes("财联社") || normalized.includes("cls")) {
    return "cls";
  }
  if (normalized.includes("东方") || normalized.includes("eastmoney")) {
    return "eastmoney";
  }
  if (
    normalized.includes("同花顺") ||
    normalized.includes("10jqka") ||
    normalized.includes("tonghuashun")
  ) {
    return "tonghuashun";
  }
  if (normalized.includes("雪球") || normalized.includes("xueqiu")) {
    return "xueqiu";
  }
  if (
    normalized.includes("第一财经") ||
    normalized.includes("yicai") ||
    normalized.includes("cbn")
  ) {
    return "yicai";
  }
  return null;
}

function normalizeSourceLabel(source: string) {
  return source || "--";
}

function resolveNewsUrl(item: NewsItem) {
  const raw = item.url.trim();
  if (raw) {
    return raw;
  }
  const sourceKey = normalizeSourceKey(item.source);
  if (sourceKey) {
    return SOURCE_HOME_URLS[sourceKey];
  }
  return "#";
}

function formatPublishedAt(timestamp: string | null, locale: string) {
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

function formatCompactNumber(value: number) {
  if (value >= 10_000) {
    return `${(value / 10_000).toFixed(value >= 100_000 ? 0 : 1)}w`;
  }
  return String(value);
}
