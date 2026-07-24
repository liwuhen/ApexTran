import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  addDefaultWatchlistItem,
  loadAiHotspots,
  loadDailyKline,
  loadDailyKlines,
  loadDefaultWatchlistItems,
  loadFlash,
  loadHeadlines,
  loadHotlist,
  loadIntraday,
  loadMarketSectorDetail,
  loadMarketSectors,
  loadQuotes,
  loadNews,
  removeDefaultWatchlistItem,
  searchStocks,
} from "./api";
import { marketRefKey, type MarketRef } from "./refs";
import type {
  KlineBar,
  MarketSectorSort,
  StockSearchItem,
  WatchlistItemWithQuote,
} from "./types";
import {
  ON_ADD_REQUOTE_DELAY_MS,
  WATCHLIST_ITEMS_QUERY_KEY,
  withOptimisticWatchlistItem,
} from "./watchlist-cache";

// Poll on an interval: the server already collapses upstream fan-out (worker →
// Redis → N readers), so a short client poll is cheap and keeps headlines fresh.
export function useHotlist({
  refetchInterval = 15_000,
  enabled = true,
}: {
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "hotlist"],
    queryFn: loadHotlist,
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    hotlist: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useStockSearch({
  query,
  limit = 20,
  refetchInterval = false,
  enabled = true,
}: {
  query: string;
  limit?: number;
  refetchInterval?: number | false;
  enabled?: boolean;
}) {
  const trimmedQuery = query.trim();
  const queryResult = useQuery({
    queryKey: ["market", "stock-search", trimmedQuery, limit],
    queryFn: () => searchStocks(trimmedQuery, limit),
    enabled: enabled && trimmedQuery.length > 0,
    refetchInterval,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  return {
    stocks: queryResult.data ?? [],
    isLoading: queryResult.isLoading,
    isFetching: queryResult.isFetching,
    error: queryResult.error,
    refetch: queryResult.refetch,
    dataUpdatedAt: queryResult.dataUpdatedAt,
  };
}

// A daily bar changes once a session, so there is nothing to gain from polling
// it on the intraday cadence — settled history is refetched slowly. The one case
// that does want a fast poll is a symbol with no stored history yet: the backend
// is backfilling it in the background, and we want to pick that up promptly.
const SETTLED_KLINE_POLL_MS = 300_000;
const AWAITING_BACKFILL_POLL_MS = 5_000;

// Charts are opened on demand from a dialog, so both hooks stay disabled — and
// poll nothing — until that dialog mounts them with `enabled`.
export function useDailyKline({
  symbol,
  market = "",
  limit = 180,
  enabled = true,
  initialBars,
}: {
  symbol: string;
  market?: string;
  limit?: number;
  enabled?: boolean;
  // Bars already loaded by the watchlist's batch read, so the dialog draws on
  // open instead of flashing a skeleton for a round trip it doesn't need.
  initialBars?: KlineBar[];
}) {
  const trimmedMarket = market.trim();
  const query = useQuery({
    queryKey: ["market", "klines", trimmedMarket, symbol, limit],
    queryFn: () => loadDailyKline(symbol, limit, trimmedMarket),
    enabled: enabled && symbol.length > 0,
    initialData: initialBars?.length ? initialBars : undefined,
    refetchInterval: (query) =>
      query.state.data?.length
        ? SETTLED_KLINE_POLL_MS
        : AWAITING_BACKFILL_POLL_MS,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    bars: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

// The watchlist's daily history in one request, keyed by "market:symbol". The
// whole list costs one query against stored history, so this scales with the
// page rather than with the number of stocks on it.
export function useDailyKlines({
  refs,
  limit = 180,
  enabled = true,
}: {
  refs: MarketRef[];
  limit?: number;
  enabled?: boolean;
}) {
  const keys = refs.map(marketRefKey);
  const query = useQuery({
    queryKey: ["market", "klines", "batch", keys, limit],
    queryFn: () => loadDailyKlines(refs, limit),
    enabled: enabled && refs.length > 0,
    refetchInterval: (query) =>
      (query.state.data?.some((series) => series.bars.length === 0) ?? true)
        ? AWAITING_BACKFILL_POLL_MS
        : SETTLED_KLINE_POLL_MS,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  const barsByRef = useMemo(() => {
    const index: Record<string, KlineBar[]> = {};
    for (const series of query.data ?? []) {
      index[marketRefKey(series)] = series.bars;
    }
    return index;
  }, [query.data]);
  return {
    barsByRef,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useIntraday({
  symbol,
  market = "",
  enabled = true,
}: {
  symbol: string;
  market?: string;
  enabled?: boolean;
}) {
  const trimmedMarket = market.trim();
  const query = useQuery({
    queryKey: ["market", "intraday", trimmedMarket, symbol],
    queryFn: () => loadIntraday(symbol, trimmedMarket),
    enabled: enabled && symbol.length > 0,
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    series: query.data ?? null,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useHeadlines({
  symbol,
  refetchInterval = 15_000,
  enabled = true,
}: {
  symbol?: string;
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "headlines", symbol ?? null],
    queryFn: () => loadHeadlines(symbol),
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    headlines: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useNews({
  category,
  refetchInterval = 15_000,
  enabled = true,
}: {
  category?: string;
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "news", category ?? null],
    queryFn: () => loadNews(category),
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    news: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useFlash({
  refetchInterval = 15_000,
  enabled = true,
}: {
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "flash"],
    queryFn: loadFlash,
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    flash: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useAiHotspots({
  refetchInterval = 15_000,
  enabled = true,
}: {
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "ai-hotspots"],
    queryFn: loadAiHotspots,
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    aiHotspots: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useMarketSectors({
  type = "concept",
  sort = "heat",
  keyword = "",
  limit = 100,
  refetchInterval = 30_000,
  enabled = true,
}: {
  type?: "concept" | "industry";
  sort?: MarketSectorSort;
  keyword?: string;
  limit?: number;
  refetchInterval?: number | false;
  enabled?: boolean;
} = {}) {
  const trimmedKeyword = keyword.trim();
  const query = useQuery({
    queryKey: ["market", "sectors", type, sort, trimmedKeyword, limit],
    queryFn: () =>
      loadMarketSectors({
        type,
        sort,
        keyword: trimmedKeyword,
        limit,
      }),
    enabled,
    refetchInterval,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    sectors: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
    dataUpdatedAt: query.dataUpdatedAt,
  };
}

export function useMarketSectorDetail({
  sectorId,
  memberLimit = 100,
  enabled = true,
}: {
  sectorId: string | null;
  memberLimit?: number;
  enabled?: boolean;
}) {
  const query = useQuery({
    queryKey: ["market", "sectors", "detail", sectorId, memberLimit],
    queryFn: () => loadMarketSectorDetail(sectorId ?? "", memberLimit),
    enabled: enabled && Boolean(sectorId),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 5_000,
  });
  return {
    detail: query.data ?? null,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useDefaultWatchlistItems({
  includeQuotes = false,
  refetchInterval = includeQuotes ? 5_000 : false,
}: {
  includeQuotes?: boolean;
  refetchInterval?: number | false;
} = {}) {
  const query = useQuery({
    queryKey: ["market", "watchlists", "default", "items", { includeQuotes }],
    queryFn: () => loadDefaultWatchlistItems({ includeQuotes }),
    refetchOnWindowFocus: true,
    refetchInterval,
    staleTime: 5_000,
    retry: false,
  });
  return {
    items: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useMarketQuotes({
  symbols,
  enabled = true,
}: {
  symbols: string[];
  enabled?: boolean;
}) {
  const normalizedSymbols = symbols.filter(Boolean);
  const query = useQuery({
    queryKey: ["market", "quotes", normalizedSymbols],
    queryFn: () => loadQuotes(normalizedSymbols),
    enabled: enabled && normalizedSymbols.length > 0,
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
    staleTime: 2_000,
  });
  return {
    quotes: query.data ?? [],
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useAddDefaultWatchlistItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (stock: StockSearchItem) => addDefaultWatchlistItem(stock),
    // Optimistic: the row appears instantly with the day-level stats the search
    // result already carries; the server round-trips replace it afterwards.
    onMutate: async (stock: StockSearchItem) => {
      await queryClient.cancelQueries({ queryKey: WATCHLIST_ITEMS_QUERY_KEY });
      const previous = queryClient.getQueriesData<WatchlistItemWithQuote[]>({
        queryKey: WATCHLIST_ITEMS_QUERY_KEY,
      });
      queryClient.setQueriesData<WatchlistItemWithQuote[]>(
        { queryKey: WATCHLIST_ITEMS_QUERY_KEY },
        (items) => withOptimisticWatchlistItem(items, stock),
      );
      return { previous };
    },
    onError: (_error, _stock, context) => {
      for (const [queryKey, data] of context?.previous ?? []) {
        queryClient.setQueryData(queryKey, data);
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: WATCHLIST_ITEMS_QUERY_KEY,
      });
      // Second pass once the backend's on-add refresh has landed the realtime
      // quote snapshot, upgrading the row from day-level to live numbers.
      setTimeout(() => {
        void queryClient.invalidateQueries({
          queryKey: WATCHLIST_ITEMS_QUERY_KEY,
        });
      }, ON_ADD_REQUOTE_DELAY_MS);
    },
  });
}

export function useRemoveDefaultWatchlistItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (stock: Pick<StockSearchItem, "market" | "symbol">) =>
      removeDefaultWatchlistItem(stock),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["market", "watchlists", "default", "items"],
      });
    },
  });
}
