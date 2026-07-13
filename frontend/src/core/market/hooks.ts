import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addDefaultWatchlistItem,
  loadAiHotspots,
  loadDailyKline,
  loadDefaultWatchlistItems,
  loadFlash,
  loadHeadlines,
  loadHotlist,
  loadIntraday,
  loadQuotes,
  loadNews,
  removeDefaultWatchlistItem,
  searchStocks,
} from "./api";
import type { StockSearchItem, WatchlistItemWithQuote } from "./types";
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

// Charts are opened on demand from a dialog, so both hooks stay disabled — and
// poll nothing — until that dialog mounts them with `enabled`.
export function useDailyKline({
  symbol,
  market = "",
  limit = 180,
  enabled = true,
}: {
  symbol: string;
  market?: string;
  limit?: number;
  enabled?: boolean;
}) {
  const trimmedMarket = market.trim();
  const query = useQuery({
    queryKey: ["market", "klines", trimmedMarket, symbol, limit],
    queryFn: () => loadDailyKline(symbol, limit, trimmedMarket),
    enabled: enabled && symbol.length > 0,
    // Aligned with the worker's 10s snapshot cycle (and the intraday poll).
    refetchInterval: 10_000,
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
