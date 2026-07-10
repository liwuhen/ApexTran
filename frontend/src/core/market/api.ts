import { getBackendBaseURL } from "../config";

import type {
  FlashItem,
  HotItem,
  NewsItem,
  StockQuoteItem,
  StockSearchItem,
  WatchlistItem,
} from "./types";

// Public, cacheable endpoint. Same-origin in the nginx stack; proxied to
// apextran-app (:8100) via the /api/v1/* rewrite in `next dev`.
export async function loadHotlist(): Promise<HotItem[]> {
  const base = getBackendBaseURL();
  const res = await fetch(`${base}/api/v1/market/hotlist`);
  if (!res.ok) {
    throw new Error(`Failed to load hotlist: ${res.status}`);
  }
  return (await res.json()) as HotItem[];
}

export async function searchStocks(
  query: string,
  limit = 20,
): Promise<StockSearchItem[]> {
  const base = getBackendBaseURL();
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  const res = await fetch(`${base}/api/v1/market/stocks/search?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to search stocks: ${res.status}`);
  }
  return (await res.json()) as StockSearchItem[];
}

export async function loadQuotes(symbols: string[]): Promise<StockQuoteItem[]> {
  if (symbols.length === 0) {
    return [];
  }
  const base = getBackendBaseURL();
  const params = new URLSearchParams({
    symbols: symbols.join(","),
  });
  const res = await fetch(`${base}/api/v1/market/quotes?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to load quotes: ${res.status}`);
  }
  return (await res.json()) as StockQuoteItem[];
}

export async function loadHeadlines(symbol?: string): Promise<NewsItem[]> {
  const base = getBackendBaseURL();
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  const res = await fetch(`${base}/api/v1/market/headlines${query}`);
  if (!res.ok) {
    throw new Error(`Failed to load headlines: ${res.status}`);
  }
  return (await res.json()) as NewsItem[];
}

export async function loadNews(category?: string): Promise<NewsItem[]> {
  const base = getBackendBaseURL();
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await fetch(`${base}/api/v1/market/news${query}`);
  if (!res.ok) {
    throw new Error(`Failed to load news: ${res.status}`);
  }
  return (await res.json()) as NewsItem[];
}

export async function loadAiHotspots(): Promise<NewsItem[]> {
  const base = getBackendBaseURL();
  const res = await fetch(`${base}/api/v1/market/ai-hotspots`);
  if (!res.ok) {
    throw new Error(`Failed to load AI hotspots: ${res.status}`);
  }
  return (await res.json()) as NewsItem[];
}

export async function loadFlash(): Promise<FlashItem[]> {
  const base = getBackendBaseURL();
  const res = await fetch(`${base}/api/v1/market/flash`);
  if (!res.ok) {
    throw new Error(`Failed to load flash: ${res.status}`);
  }
  return (await res.json()) as FlashItem[];
}

export async function loadDefaultWatchlistItems(): Promise<WatchlistItem[]> {
  const res = await fetch("/api/market/watchlists/default/items", {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to load watchlist: ${res.status}`);
  }
  return (await res.json()) as WatchlistItem[];
}

export async function addDefaultWatchlistItem(
  stock: StockSearchItem,
): Promise<WatchlistItem> {
  const res = await fetch("/api/market/watchlists/default/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: stock.symbol,
      name: stock.name,
      market: stock.market,
      concept: stock.concept,
      source: stock.source,
      updated_at: stock.updated_at,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to add watchlist item: ${res.status}`);
  }
  return (await res.json()) as WatchlistItem;
}

export async function removeDefaultWatchlistItem(symbol: string): Promise<void> {
  const res = await fetch(
    `/api/market/watchlists/default/items/${encodeURIComponent(symbol)}`,
    {
      method: "DELETE",
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to remove watchlist item: ${res.status}`);
  }
}
