"use client";

import {
  ArrowDownIcon,
  ArrowUpIcon,
  BarChart3Icon,
  FlameIcon,
  Loader2Icon,
  RefreshCwIcon,
  SearchIcon,
  TriangleAlertIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useMarketSectorDetail, useMarketSectors } from "@/core/market/hooks";
import type {
  MarketSector,
  MarketSectorMember,
  MarketSectorSort,
} from "@/core/market/types";
import { cn } from "@/lib/utils";

const SORT_OPTIONS: Array<{ key: MarketSectorSort; icon: LucideIcon }> = [
  { key: "heat", icon: FlameIcon },
  { key: "change", icon: ArrowUpIcon },
  { key: "amount", icon: BarChart3Icon },
  { key: "name", icon: UsersIcon },
];

export default function SectorAnalysisPage() {
  const { t } = useI18n();
  const [keywordInput, setKeywordInput] = useState("");
  const [sort, setSort] = useState<MarketSectorSort>("heat");
  const [selectedSectorId, setSelectedSectorId] = useState<string | null>(null);
  const keyword = useDebouncedValue(keywordInput, 180).trim();
  const sectorsQuery = useMarketSectors({
    sort,
    keyword,
    limit: 500,
    refetchInterval: 30_000,
  });
  const sectors = sectorsQuery.sectors;
  const selectedSector = useMemo(
    () => sectors.find((sector) => sector.id === selectedSectorId) ?? null,
    [sectors, selectedSectorId],
  );
  const detailQuery = useMarketSectorDetail({
    sectorId: selectedSectorId,
    memberLimit: 500,
    enabled: Boolean(selectedSectorId),
  });
  const detail = detailQuery.detail ?? selectedSector;
  const totals = useMemo(() => buildSectorTotals(sectors), [sectors]);

  useEffect(() => {
    document.title = `${t.sidebar.sectorAnalysis} - ${t.pages.appName}`;
  }, [t.sidebar.sectorAnalysis, t.pages.appName]);

  useEffect(() => {
    if (sectors.length === 0) {
      setSelectedSectorId(null);
      return;
    }
    const firstSector = sectors[0];
    if (!firstSector) {
      return;
    }
    if (
      !selectedSectorId ||
      !sectors.some((sector) => sector.id === selectedSectorId)
    ) {
      setSelectedSectorId(firstSector.id);
    }
  }, [sectors, selectedSectorId]);

  const isInitialLoading = sectorsQuery.isLoading && sectors.length === 0;
  const error = sectorsQuery.error ?? detailQuery.error;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody className="min-w-0 items-stretch">
        <ScrollArea className="size-full max-w-full min-w-0">
          <div className="flex w-full max-w-full min-w-0 flex-col gap-5 overflow-x-hidden p-6">
            <section className="flex flex-col gap-4 border-b pb-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-red-500">
                    <FlameIcon className="size-4" />
                    {t.market.autoRefreshing}
                  </div>
                  <h1 className="mt-2 text-2xl font-semibold tracking-normal">
                    {t.market.sectorTitle}
                  </h1>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {t.market.sectorSubtitle}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    void sectorsQuery.refetch();
                    if (selectedSectorId) {
                      void detailQuery.refetch();
                    }
                  }}
                  disabled={sectorsQuery.isFetching || detailQuery.isFetching}
                >
                  {sectorsQuery.isFetching || detailQuery.isFetching ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <RefreshCwIcon className="size-4" />
                  )}
                  {t.market.refresh}
                </Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <HeaderMetric
                  label={t.market.sectorList}
                  value={String(sectors.length)}
                />
                <HeaderMetric
                  label={t.market.sectorStockCount}
                  value={String(totals.stocks)}
                />
                <HeaderMetric
                  label={t.market.sectorLeaderCount}
                  value={String(totals.leaders)}
                />
                <HeaderMetric
                  label={t.market.updatedAt}
                  value={totals.updatedAt}
                />
              </div>
            </section>

            <section className="grid min-h-[620px] grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
              <div className="bg-background flex min-w-0 flex-col overflow-hidden rounded-lg border">
                <div className="flex shrink-0 flex-col border-b px-4 pt-3.5 pb-2.5">
                  <h2 className="sr-only">{t.market.sectorList}</h2>
                  <div className="relative">
                    <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                    <Input
                      value={keywordInput}
                      onChange={(event) => setKeywordInput(event.target.value)}
                      placeholder={t.market.sectorSearchPlaceholder}
                      className="h-9 pr-9 pl-9"
                    />
                    <button
                      type="button"
                      aria-label={t.market.refresh}
                      title={t.market.refresh}
                      onClick={() => void sectorsQuery.refetch()}
                      disabled={sectorsQuery.isFetching}
                      className="text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
                    >
                      <RefreshCwIcon
                        className={cn(
                          "size-3.5",
                          sectorsQuery.isFetching && "animate-spin",
                        )}
                      />
                    </button>
                  </div>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {SORT_OPTIONS.map((option) => {
                      const Icon = option.icon;
                      return (
                        <button
                          key={option.key}
                          type="button"
                          onClick={() => setSort(option.key)}
                          className={cn(
                            "inline-flex h-[26px] items-center gap-1 rounded-full border px-2.5 text-xs transition-colors",
                            "hover:border-blue-600 hover:text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none",
                            sort === option.key
                              ? "border-blue-600 bg-blue-50 font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
                              : "border-border bg-background text-muted-foreground",
                          )}
                        >
                          <Icon className="size-3" />
                          {sortLabel(option.key, t)}
                        </button>
                      );
                    })}
                  </div>
                  <div className="text-muted-foreground mt-2 flex items-center justify-between gap-3 text-[11px]">
                    <span>
                      {t.market.updatedAt} {totals.updatedAt}
                    </span>
                    <span>{t.market.results(sectors.length)}</span>
                  </div>
                </div>

                {error && sectors.length === 0 ? (
                  <Alert variant="destructive" className="m-4">
                    <TriangleAlertIcon className="size-4" />
                    <AlertTitle>{t.market.loadFailed}</AlertTitle>
                    <AlertDescription className="flex flex-col gap-3">
                      <span>{String(error.message ?? error)}</span>
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-fit"
                        onClick={() => void sectorsQuery.refetch()}
                      >
                        {t.market.retry}
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : isInitialLoading ? (
                  <div className="space-y-3 p-4">
                    {Array.from({ length: 8 }, (_, index) => (
                      <Skeleton key={index} className="h-20 rounded-lg" />
                    ))}
                  </div>
                ) : sectors.length === 0 ? (
                  <Empty className="p-10">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <BarChart3Icon className="size-6" />
                      </EmptyMedia>
                      <EmptyTitle>{t.market.sectorNoData}</EmptyTitle>
                      <EmptyDescription>
                        {t.market.autoRefreshing}
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    {sectors.map((sector) => (
                      <SectorListRow
                        key={sector.id}
                        sector={sector}
                        selected={sector.id === selectedSectorId}
                        onSelect={() => setSelectedSectorId(sector.id)}
                        t={t}
                      />
                    ))}
                  </div>
                )}
              </div>

              <div className="bg-background min-w-0 overflow-hidden rounded-lg border">
                {detail ? (
                  <SectorDetailPanel
                    sector={detail}
                    isLoading={detailQuery.isLoading}
                    t={t}
                  />
                ) : (
                  <Empty className="h-full min-h-[420px]">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <UsersIcon className="size-6" />
                      </EmptyMedia>
                      <EmptyTitle>{t.market.sectorNoSelection}</EmptyTitle>
                      <EmptyDescription>
                        {t.market.sectorNoData}
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </div>
            </section>
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function SectorListRow({
  sector,
  selected,
  onSelect,
  t,
}: {
  sector: MarketSector;
  selected: boolean;
  onSelect: () => void;
  t: ReturnType<typeof useI18n>["t"];
}) {
  const movingCount = sector.up_count + sector.down_count;
  const upRatio = movingCount > 0 ? (sector.up_count / movingCount) * 100 : 0;
  const downRatio =
    movingCount > 0 ? (sector.down_count / movingCount) * 100 : 0;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-start justify-between gap-2 border-l-[3px] px-4 py-3 text-left transition-colors",
        "hover:bg-muted/45 focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
        selected
          ? "border-l-blue-600 bg-blue-50 dark:bg-blue-950/25"
          : "border-l-transparent",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
          {sector.name}
        </div>
        {sector.leading_symbols.length ? (
          <div className="text-muted-foreground mt-0.5 truncate text-[11px]">
            {t.market.sectorLeadingStocks} ·{" "}
            {sector.leading_symbols.slice(0, 3).join(" · ")}
          </div>
        ) : null}
        <div className="text-muted-foreground mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px]">
          <span className="font-semibold whitespace-nowrap">
            {sector.stock_count} {t.market.sectorMembers}
          </span>
          <span
            className={cn(
              "font-semibold whitespace-nowrap",
              sector.limit_up_count > 0 && "text-red-500",
            )}
          >
            {t.market.sectorLimitUp} {sector.limit_up_count}
          </span>
          {movingCount > 0 ? (
            <>
              <span className="whitespace-nowrap">
                {t.market.sectorBreadth}
              </span>
              <span
                aria-label={`${t.market.sectorBreadth} ${sector.up_count}/${sector.down_count}`}
                className="bg-muted flex h-1.5 max-w-28 min-w-14 flex-1 overflow-hidden rounded-full"
              >
                <span
                  className="h-full bg-red-500"
                  style={{ flexBasis: `${upRatio}%` }}
                />
                <span
                  className="h-full bg-emerald-500"
                  style={{ flexBasis: `${downRatio}%` }}
                />
              </span>
            </>
          ) : null}
        </div>
      </div>
      <div className="flex min-w-16 shrink-0 flex-col items-end gap-0.5 pt-0.5 tabular-nums">
        <span
          className={cn(
            "text-[15px] leading-tight font-bold",
            changeClassName(sector.avg_change_pct),
          )}
        >
          {formatPct(sector.avg_change_pct)}
        </span>
        <span className="text-muted-foreground text-[10px]">
          {t.market.heat} {formatNumber(sector.heat_score)}
        </span>
      </div>
    </button>
  );
}

function SectorDetailPanel({
  sector,
  isLoading,
  t,
}: {
  sector: MarketSector & { members?: MarketSectorMember[] };
  isLoading: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  const members = sector.members ?? [];
  const roleCounts = countRoles(members);

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="border-b p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-muted-foreground text-xs">
              {t.market.updatedAt}{" "}
              {formatTime(sector.snapshot_at ?? sector.updated_at)}
            </div>
            <h2 className="mt-1 truncate text-2xl font-semibold">
              {sector.name}
            </h2>
          </div>
          <div className="text-right">
            <div className="text-muted-foreground text-xs">{t.market.heat}</div>
            <div className="text-2xl font-semibold">
              {formatNumber(sector.heat_score)}
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <DetailMetric
            label={t.market.sectorStockCount}
            value={String(sector.stock_count)}
          />
          <DetailMetric
            label={t.market.sectorRoleLeader}
            value={String(roleCounts.leader)}
          />
          <DetailMetric
            label={t.market.sectorRoleCenter}
            value={String(roleCounts.center)}
          />
          <DetailMetric
            label={`${t.market.sectorRoleFollower}/${t.market.sectorRoleCatchUp}`}
            value={`${roleCounts.follower}/${roleCounts.catchUp}`}
          />
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground text-sm">
            {t.market.sectorLeadingStocks}
          </span>
          {sector.leading_symbols.length ? (
            sector.leading_symbols.map((symbol) => (
              <Badge key={symbol} variant="secondary">
                {symbol}
              </Badge>
            ))
          ) : (
            <span className="text-muted-foreground text-sm">--</span>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="text-muted-foreground grid grid-cols-[minmax(120px,1fr)_76px_72px_76px_90px_minmax(120px,1fr)] gap-3 border-b px-5 py-3 text-xs font-medium">
          <div>{t.market.stock}</div>
          <div>{t.market.sectorRole}</div>
          <div className="text-right">{t.market.price}</div>
          <div className="text-right">{t.market.changePct}</div>
          <div className="text-right">{t.market.amount}</div>
          <div>{t.market.sectorCatalyst}</div>
        </div>
        {isLoading && members.length === 0 ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 8 }, (_, index) => (
              <Skeleton key={index} className="h-12 rounded-lg" />
            ))}
          </div>
        ) : members.length === 0 ? (
          <Empty className="min-h-[300px]">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <UsersIcon className="size-6" />
              </EmptyMedia>
              <EmptyTitle>{t.market.sectorMembers}</EmptyTitle>
              <EmptyDescription>{t.market.sectorNoData}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            {members.map((member) => (
              <MemberRow
                key={`${member.market}:${member.symbol}`}
                member={member}
                t={t}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MemberRow({
  member,
  t,
}: {
  member: MarketSectorMember;
  t: ReturnType<typeof useI18n>["t"];
}) {
  return (
    <div className="grid grid-cols-[minmax(120px,1fr)_76px_72px_76px_90px_minmax(120px,1fr)] gap-3 border-b px-5 py-3 text-sm">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium">
            {member.name || member.symbol}
          </span>
        </div>
        <div className="text-muted-foreground mt-0.5 text-xs">
          {member.symbol}
        </div>
      </div>
      <div>
        <Badge
          variant="secondary"
          className={cn("h-6", roleClassName(member.role))}
        >
          {roleLabel(member.role, t)}
        </Badge>
      </div>
      <div className="text-right tabular-nums">
        {formatPrice(member.latest_price)}
      </div>
      <div
        className={cn(
          "text-right font-medium tabular-nums",
          changeClassName(member.change_pct),
        )}
      >
        {member.change_pct !== null && member.change_pct >= 0 ? (
          <ArrowUpIcon className="mr-1 inline size-3" />
        ) : member.change_pct !== null ? (
          <ArrowDownIcon className="mr-1 inline size-3" />
        ) : null}
        {formatPct(member.change_pct)}
      </div>
      <div className="text-right tabular-nums">
        {formatLargeAmount(member.amount)}
      </div>
      <div className="text-muted-foreground min-w-0 truncate">
        {member.reason || "--"}
      </div>
    </div>
  );
}

function HeaderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-background rounded-lg border px-4 py-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function DetailMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: number | null;
}) {
  return (
    <div className="rounded-lg border px-4 py-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div
        className={cn(
          "mt-1 text-lg font-semibold",
          tone !== undefined && changeClassName(tone),
        )}
      >
        {value}
      </div>
    </div>
  );
}

function buildSectorTotals(sectors: MarketSector[]) {
  const totals = sectors.reduce(
    (current, sector) => ({
      stocks: current.stocks + sector.stock_count,
      leaders: current.leaders + (sector.leading_symbols.length > 0 ? 1 : 0),
      latest: newestTime(
        current.latest,
        sector.snapshot_at ?? sector.updated_at,
      ),
    }),
    { stocks: 0, leaders: 0, latest: null as string | null },
  );
  return { ...totals, updatedAt: formatTime(totals.latest) };
}

function sortLabel(key: MarketSectorSort, t: ReturnType<typeof useI18n>["t"]) {
  if (key === "change") {
    return t.market.changePct;
  }
  if (key === "amount") {
    return t.market.amount;
  }
  if (key === "leaders") {
    return t.market.sectorRoleLeader;
  }
  if (key === "name") {
    return t.market.concept;
  }
  return t.market.heat;
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  return value.toFixed(2);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  return value >= 1000 ? value.toFixed(0) : value.toFixed(1);
}

function formatLargeAmount(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "--";
  }
  const absValue = Math.abs(value);
  if (absValue >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(2)}亿`;
  }
  if (absValue >= 10_000) {
    return `${(value / 10_000).toFixed(2)}万`;
  }
  return value.toFixed(2);
}

function formatTime(value: string | null | undefined) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function newestTime(left: string | null, right: string | null | undefined) {
  if (!right) {
    return left;
  }
  if (!left) {
    return right;
  }
  return new Date(right).getTime() > new Date(left).getTime() ? right : left;
}

function changeClassName(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "text-muted-foreground";
  }
  return value >= 0 ? "text-red-500" : "text-emerald-600 dark:text-emerald-400";
}

function roleLabel(role: string, t: ReturnType<typeof useI18n>["t"]) {
  if (role === "leader") {
    return t.market.sectorRoleLeader;
  }
  if (role === "center") {
    return t.market.sectorRoleCenter;
  }
  if (role === "follower" || role === "core") {
    return t.market.sectorRoleFollower;
  }
  if (role === "catch_up") {
    return t.market.sectorRoleCatchUp;
  }
  return t.market.sectorRoleMember;
}

function roleClassName(role: string) {
  if (role === "leader") {
    return "bg-red-500 text-white hover:bg-red-500";
  }
  if (role === "center") {
    return "bg-amber-500 text-white hover:bg-amber-500";
  }
  if (role === "follower" || role === "core") {
    return "bg-blue-500 text-white hover:bg-blue-500";
  }
  if (role === "catch_up") {
    return "bg-violet-500 text-white hover:bg-violet-500";
  }
  return "";
}

function countRoles(members: MarketSectorMember[]) {
  return members.reduce(
    (counts, member) => {
      if (member.role === "leader") {
        counts.leader += 1;
      } else if (member.role === "center") {
        counts.center += 1;
      } else if (member.role === "follower" || member.role === "core") {
        counts.follower += 1;
      } else if (member.role === "catch_up") {
        counts.catchUp += 1;
      }
      return counts;
    },
    { leader: 0, center: 0, follower: 0, catchUp: 0 },
  );
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);

  return debounced;
}
