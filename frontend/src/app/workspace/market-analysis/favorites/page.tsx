"use client";

import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  Loader2Icon,
  RefreshCwIcon,
  SearchIcon,
  SparklesIcon,
  StarIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  StockChartDialogHost,
  useStockChartDialog,
} from "@/components/workspace/market";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  useAddDefaultWatchlistItem,
  useDailyKlines,
  useDefaultWatchlistItems,
  useRemoveDefaultWatchlistItem,
  useStockSearch,
} from "@/core/market/hooks";
import { marketRefKey } from "@/core/market/refs";
import type { StockSearchItem } from "@/core/market/types";
import { cn } from "@/lib/utils";

const SEARCH_LIMIT = 20;
const FAVORITE_PAGE_SIZE_OPTIONS = [10, 20, 30] as const;

type FavoriteStock = StockSearchItem & { addedAt: string };
type FavoritePageSize = (typeof FAVORITE_PAGE_SIZE_OPTIONS)[number];
type FavoriteSortKey =
  | "latest_price"
  | "change_pct"
  | "turnover_rate"
  | "amount"
  | "float_market_cap"
  | "total_market_cap";
type FavoriteSort = {
  key: FavoriteSortKey;
  direction: "asc" | "desc";
};

export default function FavoritesPage() {
  const { t } = useI18n();
  const [searchInput, setSearchInput] = useState("");
  const [isSearchMenuOpen, setIsSearchMenuOpen] = useState(false);
  const searchAreaRef = useRef<HTMLDivElement | null>(null);
  const [favoriteSort, setFavoriteSort] = useState<FavoriteSort | null>(null);
  const stockChartDialog = useStockChartDialog();
  const [favoritePage, setFavoritePage] = useState(1);
  const [favoritePageSize, setFavoritePageSize] =
    useState<FavoritePageSize>(30);
  const searchQuery = useDebouncedValue(searchInput, 180).trim();
  const { stocks, isLoading, isFetching, error, refetch } = useStockSearch({
    query: searchQuery,
    limit: SEARCH_LIMIT,
    enabled: searchQuery.length > 0,
  });
  const watchlist = useDefaultWatchlistItems({ includeQuotes: true });
  const addWatchlistItem = useAddDefaultWatchlistItem();
  const removeWatchlistItem = useRemoveDefaultWatchlistItem();
  const favorites = useMemo(
    () =>
      watchlist.items.map((item) => {
        const quote = item.quote;
        return {
          ...item.instrument,
          latest_price: quote?.latest_price ?? item.instrument.latest_price,
          change_pct: quote?.change_pct ?? item.instrument.change_pct,
          turnover_rate: quote?.turnover_rate ?? item.instrument.turnover_rate,
          amount: quote?.amount ?? item.instrument.amount,
          float_market_cap:
            quote?.float_market_cap ?? item.instrument.float_market_cap,
          total_market_cap:
            quote?.total_market_cap ?? item.instrument.total_market_cap,
          source: quote?.source ?? item.instrument.source,
          updated_at: quote?.updated_at ?? item.instrument.updated_at,
          addedAt: item.created_at,
        };
      }),
    [watchlist.items],
  );

  useEffect(() => {
    document.title = `${t.sidebar.favorites} - ${t.pages.appName}`;
  }, [t.sidebar.favorites, t.pages.appName]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!searchAreaRef.current?.contains(event.target as Node)) {
        setIsSearchMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  const favoriteRefs = useMemo(
    () => new Set(favorites.map(marketRefKey)),
    [favorites],
  );
  const sortedFavorites = useMemo(
    () =>
      favoriteSort
        ? [...favorites].sort((left, right) =>
            compareFavoriteStocks(left, right, favoriteSort),
          )
        : favorites,
    [favoriteSort, favorites],
  );
  const favoriteTotalPages = Math.max(
    1,
    Math.ceil(sortedFavorites.length / favoritePageSize),
  );
  const paginatedFavorites = useMemo(() => {
    const start = (favoritePage - 1) * favoritePageSize;
    return sortedFavorites.slice(start, start + favoritePageSize);
  }, [favoritePage, favoritePageSize, sortedFavorites]);
  // The visible page's daily history, batch-read from the backend's stored
  // K-line table in one request — so opening any row's chart draws instantly.
  const klineRefs = useMemo(
    () =>
      paginatedFavorites.map((stock) => ({
        market: stock.market,
        symbol: stock.symbol,
      })),
    [paginatedFavorites],
  );
  const dailyKlines = useDailyKlines({ refs: klineRefs });

  useEffect(() => {
    setFavoritePage(1);
  }, [favoriteSort, favoritePageSize]);

  useEffect(() => {
    setFavoritePage((current) => Math.min(current, favoriteTotalPages));
  }, [favoriteTotalPages]);

  const toggleFavoriteSort = (key: FavoriteSortKey) => {
    setFavoriteSort((current) => ({
      key,
      direction:
        current?.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const addFavorite = (stock: StockSearchItem) => {
    if (favoriteRefs.has(marketRefKey(stock)) || addWatchlistItem.isPending) {
      return;
    }
    addWatchlistItem.mutate(stock);
    setIsSearchMenuOpen(false);
  };

  const removeFavorite = (stock: FavoriteStock) => {
    removeWatchlistItem.mutate(stock);
  };

  const showSearchSkeleton =
    searchQuery.length > 0 &&
    (isLoading || (isFetching && stocks.length === 0));
  const isMutatingWatchlist =
    addWatchlistItem.isPending || removeWatchlistItem.isPending;
  const watchlistError =
    watchlist.error ?? addWatchlistItem.error ?? removeWatchlistItem.error;
  const isRefreshing =
    watchlist.isFetching ||
    (searchQuery ? isFetching : false);

  const refreshFavorites = () => {
    void watchlist.refetch();
    if (searchQuery) {
      void refetch();
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody className="min-w-0 items-stretch">
        <ScrollArea className="size-full max-w-full min-w-0">
          <div className="flex w-full max-w-full min-w-0 flex-col gap-5 overflow-x-hidden p-6">
            <section className="relative z-20 overflow-visible rounded-[28px] border bg-[radial-gradient(circle_at_top_left,_rgba(255,112,67,0.22),_transparent_32%),linear-gradient(135deg,_rgba(15,23,42,1),_rgba(23,37,84,0.96)_42%,_rgba(88,28,135,0.9))] p-6 text-white shadow-[0_20px_80px_rgba(15,23,42,0.3)]">
              <div className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(120deg,transparent,rgba(255,255,255,0.06),transparent)]" />
              <div className="relative flex flex-col gap-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-orange-200">
                    <SparklesIcon className="size-4" />
                    {t.market.autoRefreshing}
                  </div>
                  <Button
                    variant="secondary"
                    onClick={refreshFavorites}
                    disabled={isRefreshing}
                    className="w-fit border-white/15 bg-white/10 text-white hover:bg-white/16"
                  >
                    <RefreshCwIcon
                      className={cn("size-4", isRefreshing && "animate-spin")}
                    />
                    {t.market.refresh}
                  </Button>
                </div>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex max-w-3xl flex-wrap items-baseline gap-x-3 gap-y-1">
                    <div className="flex items-center gap-2">
                      <StarIcon className="size-5 text-orange-200" />
                      <h1 className="text-3xl font-semibold tracking-tight">
                        {t.market.favoriteTitle}
                      </h1>
                    </div>
                    <p className="max-w-xl text-sm leading-6 text-slate-200">
                      {t.market.favoriteSubtitle}
                    </p>
                  </div>
                  <div ref={searchAreaRef} className="relative z-30 w-full max-w-52">
                    <div className="flex items-center gap-3 rounded-2xl border border-white/12 bg-white/10 px-4 py-3 backdrop-blur">
                      <SearchIcon className="size-4 shrink-0 text-slate-300" />
                      <Input
                        value={searchInput}
                        onChange={(event) => {
                          setSearchInput(event.target.value);
                          setIsSearchMenuOpen(true);
                        }}
                        onFocus={() => setIsSearchMenuOpen(true)}
                        onClick={() => setIsSearchMenuOpen(true)}
                        placeholder={t.market.favoriteSearchPlaceholder}
                        aria-label={t.market.favoriteSearchPlaceholder}
                        className="h-auto border-0 bg-transparent px-0 py-0 text-white shadow-none placeholder:text-slate-300 focus-visible:ring-0"
                      />
                      {isFetching && searchQuery ? (
                        <Loader2Icon className="size-4 animate-spin text-slate-300" />
                      ) : null}
                    </div>
                    {searchQuery && isSearchMenuOpen ? (
                      <SearchResultsMenu
                        stocks={stocks}
                        loading={showSearchSkeleton}
                        error={error}
                        isFetching={isFetching}
                        favoriteRefs={favoriteRefs}
                        disabled={isMutatingWatchlist}
                        query={searchQuery}
                        onAdd={addFavorite}
                        onRetry={() => refetch()}
                      />
                    ) : null}
                  </div>
                </div>
              </div>
            </section>

            <section className="relative z-0 min-h-[560px] w-full max-w-full min-w-0">
              <Card className="w-full max-w-full min-w-0 gap-0 overflow-hidden py-0">
                <CardHeader className="border-b px-5 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="text-base">
                      {t.market.favoriteList}
                    </CardTitle>
                    <Badge variant="secondary">{favorites.length}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="min-h-0 min-w-0 flex-1 px-0">
                  {watchlistError ? (
                    <div className="p-5">
                      <Alert variant="destructive">
                        <TriangleAlertIcon />
                        <AlertTitle>{t.market.loadFailed}</AlertTitle>
                        <AlertDescription>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => watchlist.refetch()}
                            disabled={watchlist.isFetching}
                            className="mt-3"
                          >
                            {t.market.retry}
                          </Button>
                        </AlertDescription>
                      </Alert>
                    </div>
                  ) : watchlist.isLoading ? (
                    <FavoriteListSkeleton />
                  ) : favorites.length === 0 ? (
                    <Empty className="min-h-96 border-0">
                      <EmptyHeader>
                        <EmptyMedia variant="icon">
                          <StarIcon />
                        </EmptyMedia>
                        <EmptyTitle>{t.market.emptyFavoritesTitle}</EmptyTitle>
                        <EmptyDescription>
                          {t.market.emptyFavoritesDescription}
                        </EmptyDescription>
                      </EmptyHeader>
                    </Empty>
                  ) : (
                    <FavoriteStockTable
                      stocks={paginatedFavorites}
                      totalCount={sortedFavorites.length}
                      page={favoritePage}
                      pageSize={favoritePageSize}
                      pageSizeOptions={FAVORITE_PAGE_SIZE_OPTIONS}
                      sort={favoriteSort}
                      disabled={isMutatingWatchlist}
                      onSortChange={toggleFavoriteSort}
                      onPageChange={setFavoritePage}
                      onPageSizeChange={setFavoritePageSize}
                      onSelect={stockChartDialog.open}
                      onRemove={removeFavorite}
                    />
                  )}
                </CardContent>
              </Card>
            </section>
          </div>
        </ScrollArea>
      </WorkspaceBody>
      <StockChartDialogHost
        controller={stockChartDialog}
        barsByRef={dailyKlines.barsByRef}
      />
    </WorkspaceContainer>
  );
}

function SearchResultsMenu({
  stocks,
  loading,
  error,
  isFetching,
  favoriteRefs,
  disabled,
  query,
  onAdd,
  onRetry,
}: {
  stocks: StockSearchItem[];
  loading: boolean;
  error: Error | null;
  isFetching: boolean;
  favoriteRefs: Set<string>;
  disabled: boolean;
  query: string;
  onAdd: (stock: StockSearchItem) => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="bg-popover text-popover-foreground absolute right-0 left-0 z-50 mt-2 overflow-hidden rounded-lg border shadow-lg">
      {error && stocks.length === 0 ? (
        <div className="p-3">
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>{t.market.loadFailed}</AlertTitle>
            <AlertDescription>
              <Button
                variant="outline"
                size="sm"
                onClick={onRetry}
                disabled={isFetching}
                className="mt-3"
              >
                {t.market.retry}
              </Button>
            </AlertDescription>
          </Alert>
        </div>
      ) : loading ? (
        <SearchResultSkeleton />
      ) : stocks.length === 0 ? (
        <div className="px-4 py-5 text-center">
          <div className="text-sm font-medium">{t.market.noStockResults}</div>
          <div className="text-muted-foreground mt-1 truncate text-xs">
            {query}
          </div>
        </div>
      ) : (
        <div className="max-h-[420px] divide-y overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {stocks.map((stock) => (
            <SearchResultRow
              key={marketRefKey(stock)}
              stock={stock}
              added={favoriteRefs.has(marketRefKey(stock))}
              disabled={disabled}
              onAdd={() => onAdd(stock)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function useDebouncedValue(value: string, delayMs: number) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timeout);
  }, [delayMs, value]);

  return debounced;
}

function FavoriteStockTable({
  stocks,
  totalCount,
  page,
  pageSize,
  pageSizeOptions,
  sort,
  disabled,
  onSortChange,
  onPageChange,
  onPageSizeChange,
  onSelect,
  onRemove,
}: {
  stocks: FavoriteStock[];
  totalCount: number;
  page: number;
  pageSize: FavoritePageSize;
  pageSizeOptions: readonly FavoritePageSize[];
  sort: FavoriteSort | null;
  disabled: boolean;
  onSortChange: (key: FavoriteSortKey) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: FavoritePageSize) => void;
  onSelect: (stock: FavoriteStock) => void;
  onRemove: (stock: FavoriteStock) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="w-full max-w-full min-w-0 overflow-hidden">
      <div className="[&::-webkit-scrollbar-thumb]:bg-border [&::-webkit-scrollbar-track]:bg-muted/30 max-h-[calc(100vh-26rem)] w-full max-w-full min-w-0 overflow-auto [scrollbar-width:thin] [&::-webkit-scrollbar]:h-2 [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full">
        <div className="min-w-[980px]">
          <table className="w-full table-fixed text-sm">
            <thead className="bg-muted/40 text-muted-foreground sticky top-0 z-10">
              <tr className="border-b">
                <th className="w-[230px] px-5 py-0 text-xs font-medium">
                  <div className="flex items-center gap-3">
                    <span className="size-10 shrink-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1 -translate-x-12 text-center">
                      {t.market.stock}
                    </span>
                  </div>
                </th>
                <SortableTableHeader
                  label={t.market.latestPrice}
                  sortKey="latest_price"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <SortableTableHeader
                  label={t.market.changePct}
                  sortKey="change_pct"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <SortableTableHeader
                  label={t.market.turnoverRate}
                  sortKey="turnover_rate"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <SortableTableHeader
                  label={t.market.amount}
                  sortKey="amount"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <SortableTableHeader
                  label={t.market.floatMarketCap}
                  sortKey="float_market_cap"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <SortableTableHeader
                  label={t.market.totalMarketCap}
                  sortKey="total_market_cap"
                  sort={sort}
                  onSortChange={onSortChange}
                />
                <th className="w-14 px-5 py-0" aria-label={t.common.delete} />
              </tr>
            </thead>
            <tbody className="divide-y">
              {stocks.map((stock) => (
                <tr
                  key={marketRefKey(stock)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${stock.name} ${t.market.viewChart}`}
                  onClick={() => onSelect(stock)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(stock);
                    }
                  }}
                  className="hover:bg-accent/40 focus-visible:ring-ring/50 cursor-pointer transition-colors outline-none focus-visible:ring-[3px]"
                >
                  <td className="px-5 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <StockAvatar symbol={stock.symbol} />
                      <StockName stock={stock} />
                    </div>
                  </td>
                  <MarketNumberCell value={formatPrice(stock.latest_price)} />
                  <MarketNumberCell
                    value={formatPct(stock.change_pct)}
                    className={changeClassName(stock.change_pct)}
                  />
                  <MarketNumberCell value={formatPct(stock.turnover_rate)} />
                  <MarketNumberCell value={formatLargeAmount(stock.amount)} />
                  <MarketNumberCell
                    value={formatLargeAmount(stock.float_market_cap)}
                  />
                  <MarketNumberCell
                    value={formatLargeAmount(stock.total_market_cap)}
                  />
                  <td className="px-5 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={(event) => {
                        // The row opens the chart dialog; deleting must not.
                        event.stopPropagation();
                        onRemove(stock);
                      }}
                      disabled={disabled}
                      aria-label={t.common.delete}
                      className="text-muted-foreground hover:text-destructive size-8 -translate-x-2"
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <FavoriteTablePagination
        totalCount={totalCount}
        page={page}
        pageSize={pageSize}
        pageSizeOptions={pageSizeOptions}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </div>
  );
}

function FavoriteTablePagination({
  totalCount,
  page,
  pageSize,
  pageSizeOptions,
  onPageChange,
  onPageSizeChange,
}: {
  totalCount: number;
  page: number;
  pageSize: FavoritePageSize;
  pageSizeOptions: readonly FavoritePageSize[];
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: FavoritePageSize) => void;
}) {
  const { t } = useI18n();
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const start = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  const pageItems = buildPaginationItems(page, totalPages);
  const [jumpPageInput, setJumpPageInput] = useState(String(page));

  useEffect(() => {
    setJumpPageInput(String(page));
  }, [page]);

  const jumpToPage = () => {
    const parsedPage = Number.parseInt(jumpPageInput, 10);
    if (!Number.isFinite(parsedPage)) {
      setJumpPageInput(String(page));
      return;
    }

    const nextPage = Math.min(totalPages, Math.max(1, parsedPage));
    onPageChange(nextPage);
    setJumpPageInput(String(nextPage));
  };

  return (
    <div className="flex flex-col gap-3 border-t px-5 py-3 text-sm sm:flex-row sm:items-center sm:justify-between">
      <div className="text-muted-foreground flex flex-wrap items-center gap-2">
        <span>{t.market.favoritePageSummary(start, end, totalCount)}</span>
        <span className="bg-border h-4 w-px" aria-hidden="true" />
        <div className="flex items-center gap-1">
          {pageSizeOptions.map((option) => (
            <Button
              key={option}
              type="button"
              variant={option === pageSize ? "secondary" : "ghost"}
              size="sm"
              onClick={() => onPageSizeChange(option)}
              className="h-7 px-2 text-xs"
            >
              {t.market.favoriteItemsPerPage(option)}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1}
            aria-label={t.market.favoritePreviousPage}
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
          {pageItems.map((item, index) =>
            item === "ellipsis" ? (
              <span
                key={`${item}-${index}`}
                className="text-muted-foreground flex size-8 items-center justify-center text-xs"
              >
                ...
              </span>
            ) : (
              <Button
                key={item}
                type="button"
                variant={item === page ? "default" : "outline"}
                size="icon"
                className="size-8 text-xs"
                onClick={() => onPageChange(item)}
                aria-label={t.market.favoritePageLabel(item)}
              >
                {item}
              </Button>
            ),
          )}
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8"
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
            aria-label={t.market.favoriteNextPage}
          >
            <ChevronRightIcon className="size-4" />
          </Button>
        </div>

        <div className="flex items-center gap-1">
          <Input
            type="number"
            min={1}
            max={totalPages}
            value={jumpPageInput}
            onChange={(event) => setJumpPageInput(event.target.value)}
            onBlur={jumpToPage}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                jumpToPage();
              }
            }}
            aria-label={t.market.favoriteJumpPage}
            className="h-8 w-16 px-2 text-center text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
            onClick={jumpToPage}
          >
            {t.market.favoriteJumpPageAction}
          </Button>
        </div>
      </div>
    </div>
  );
}

function SortableTableHeader({
  label,
  sortKey,
  sort,
  className,
  onSortChange,
}: {
  label: string;
  sortKey: FavoriteSortKey;
  sort: FavoriteSort | null;
  className?: string;
  onSortChange: (key: FavoriteSortKey) => void;
}) {
  const isActive = sort?.key === sortKey;
  const SortIcon = isActive
    ? sort.direction === "asc"
      ? ArrowUpIcon
      : ArrowDownIcon
    : ArrowUpDownIcon;

  return (
    <th className={cn("px-3 py-0 text-right font-medium", className)}>
      <button
        type="button"
        className={cn(
          "hover:bg-accent focus-visible:ring-ring/50 inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs transition-colors outline-none focus-visible:ring-[3px]",
          "ml-auto",
          "translate-x-2",
          isActive ? "text-foreground" : "text-muted-foreground",
        )}
        onClick={() => onSortChange(sortKey)}
      >
        <span>{label}</span>
        <SortIcon className="size-3.5" />
      </button>
    </th>
  );
}

function MarketNumberCell({
  value,
  className,
}: {
  value: string;
  className?: string;
}) {
  return (
    <td
      className={cn(
        "-translate-x-2 px-3 py-3 text-right font-medium tabular-nums",
        className,
      )}
    >
      {value}
    </td>
  );
}

function SearchResultRow({
  stock,
  added,
  disabled,
  onAdd,
}: {
  stock: StockSearchItem;
  added: boolean;
  disabled: boolean;
  onAdd: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={stock.name}
      aria-disabled={added || disabled}
      disabled={added || disabled}
      className="hover:bg-accent/40 focus-visible:ring-ring/50 flex w-full min-w-0 items-center gap-3 px-4 py-3 text-left text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] disabled:cursor-default disabled:opacity-50"
      onClick={onAdd}
    >
      <span className="min-w-0 flex-1 truncate">{stock.name}</span>
      <span className="text-muted-foreground shrink-0 text-xs">
        {stock.symbol}
      </span>
    </button>
  );
}

function StockAvatar({ symbol }: { symbol: string }) {
  return (
    <div className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg text-xs font-semibold">
      {symbol.slice(0, 2)}
    </div>
  );
}

function StockName({
  stock,
}: {
  stock: Pick<StockSearchItem, "name" | "symbol">;
}) {
  return (
    <div className="min-w-0">
      <div className="truncate font-semibold">{stock.name}</div>
      <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-2 text-xs">
        <span>{stock.symbol}</span>
      </div>
    </div>
  );
}

function SearchResultSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="px-4 py-3">
          <Skeleton className="h-5 w-32" />
        </div>
      ))}
    </div>
  );
}

function FavoriteListSkeleton() {
  return (
    <div className="divide-y">
      <div className="bg-muted/40 grid grid-cols-[230px_repeat(6,minmax(100px,1fr))_56px] gap-0 border-b px-5 py-3">
        {Array.from({ length: 7 }).map((_, index) => (
          <Skeleton key={index} className="h-4 w-16 justify-self-end" />
        ))}
      </div>
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={index}
          className="grid grid-cols-[230px_repeat(6,minmax(100px,1fr))_56px] items-center gap-0 px-5 py-4"
        >
          <Skeleton className="size-10 rounded-lg" />
          {Array.from({ length: 6 }).map((_, itemIndex) => (
            <Skeleton key={itemIndex} className="h-4 w-14 justify-self-end" />
          ))}
          <Skeleton className="size-8 justify-self-end rounded-md" />
        </div>
      ))}
    </div>
  );
}

function compareFavoriteStocks(
  left: FavoriteStock,
  right: FavoriteStock,
  sort: FavoriteSort,
) {
  const leftValue = numericSortValue(left, sort.key);
  const rightValue = numericSortValue(right, sort.key);
  if (leftValue === null && rightValue === null) {
    return left.symbol.localeCompare(right.symbol);
  }
  if (leftValue === null) {
    return 1;
  }
  if (rightValue === null) {
    return -1;
  }

  const valueCompare = leftValue - rightValue;
  if (valueCompare === 0) {
    return left.symbol.localeCompare(right.symbol);
  }
  return sort.direction === "asc" ? valueCompare : -valueCompare;
}

function numericSortValue(stock: FavoriteStock, key: FavoriteSortKey) {
  const value = stock[key];
  return value === null || value === undefined || !Number.isFinite(value)
    ? null
    : value;
}

function buildPaginationItems(page: number, totalPages: number) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set([1, totalPages, page - 1, page, page + 1]);
  const items: Array<number | "ellipsis"> = [];
  let lastPage = 0;

  for (const item of [...pages].sort((a, b) => a - b)) {
    if (item < 1 || item > totalPages) {
      continue;
    }
    if (lastPage > 0 && item - lastPage > 1) {
      items.push("ellipsis");
    }
    items.push(item);
    lastPage = item;
  }

  return items;
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

function changeClassName(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "text-muted-foreground";
  }
  return value >= 0 ? "text-red-500" : "text-emerald-600 dark:text-emerald-400";
}
