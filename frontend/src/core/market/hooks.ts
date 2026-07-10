import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addDefaultWatchlistItem,
  loadAiHotspots,
  loadDefaultWatchlistItems,
  loadFlash,
  loadHeadlines,
  loadHotlist,
  loadQuotes,
  loadNews,
  removeDefaultWatchlistItem,
  searchStocks,
} from "./api";
import type { StockSearchItem } from "./types";

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

export function useDefaultWatchlistItems() {
  const query = useQuery({
    queryKey: ["market", "watchlists", "default", "items"],
    queryFn: loadDefaultWatchlistItems,
    refetchOnWindowFocus: true,
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
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["market", "watchlists", "default", "items"],
      });
    },
  });
}

export function useRemoveDefaultWatchlistItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => removeDefaultWatchlistItem(symbol),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["market", "watchlists", "default", "items"],
      });
    },
  });
}
