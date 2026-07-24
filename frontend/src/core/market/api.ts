import { getBackendBaseURL } from "../config";

import { marketRef, type MarketRef } from "./refs";
import type {
  FlashItem,
  HotItem,
  IntradaySeries,
  KlineBar,
  MarketSector,
  MarketSectorDetail,
  MarketSectorMember,
  MarketSectorSort,
  NewsItem,
  StockQuoteItem,
  StockSearchItem,
  SymbolKlineSeries,
  WatchlistItem,
  WatchlistItemWithQuote,
} from "./types";

type MarketStatFields = Pick<
  StockQuoteItem,
  "turnover_rate" | "amount" | "float_market_cap" | "total_market_cap"
>;
type MarketStatKey = keyof MarketStatFields;
type MarketStatWireFields = Partial<Record<MarketStatKey, unknown>>;
type MarketItemWire<T> = Omit<T, MarketStatKey> & MarketStatWireFields;
type MarketSectorWire = Omit<
  MarketSector,
  "amount" | "avg_change_pct" | "max_change_pct"
> & {
  amount?: unknown;
  avg_change_pct?: unknown;
  max_change_pct?: unknown;
};
type MarketSectorMemberWire = Omit<
  MarketSectorMember,
  "amount" | "turnover_rate" | "change_pct"
> & {
  amount?: unknown;
  turnover_rate?: unknown;
  change_pct?: unknown;
};
type MarketSectorDetailWire = Omit<MarketSectorWire, "members"> & {
  members: MarketSectorMemberWire[];
};

function finiteNumberOrNull(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value !== "string" || value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function normalizeMarketStatFields<T extends object>(
  item: T & MarketStatWireFields,
): Omit<T, MarketStatKey> & MarketStatFields {
  return {
    ...item,
    turnover_rate: finiteNumberOrNull(item.turnover_rate),
    amount: finiteNumberOrNull(item.amount),
    float_market_cap: finiteNumberOrNull(item.float_market_cap),
    total_market_cap: finiteNumberOrNull(item.total_market_cap),
  };
}

function normalizeMarketSector(item: MarketSectorWire): MarketSector {
  return {
    ...item,
    amount: finiteNumberOrNull(item.amount),
    avg_change_pct: finiteNumberOrNull(item.avg_change_pct),
    max_change_pct: finiteNumberOrNull(item.max_change_pct),
  };
}

function normalizeMarketSectorMember(
  item: MarketSectorMemberWire,
): MarketSectorMember {
  return {
    ...item,
    amount: finiteNumberOrNull(item.amount),
    turnover_rate: finiteNumberOrNull(item.turnover_rate),
    change_pct: finiteNumberOrNull(item.change_pct),
  };
}

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
  const items = (await res.json()) as MarketItemWire<StockSearchItem>[];
  return items.map(normalizeMarketStatFields);
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
  const items = (await res.json()) as MarketItemWire<StockQuoteItem>[];
  return items.map(normalizeMarketStatFields);
}

export async function loadDailyKline(
  symbol: string,
  limit = 180,
  market = "",
): Promise<KlineBar[]> {
  const base = getBackendBaseURL();
  const params = new URLSearchParams({ limit: String(limit) });
  if (market.trim()) {
    params.set("market", market.trim());
  }
  const res = await fetch(
    `${base}/api/v1/market/klines/${encodeURIComponent(symbol)}?${params}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load daily kline: ${res.status}`);
  }
  return (await res.json()) as KlineBar[];
}

// One request for a whole watchlist. The backend serves this from stored daily
// history, so the cost is a single query no matter how many symbols are asked
// for — never N upstream calls.
export async function loadDailyKlines(
  refs: MarketRef[],
  limit = 180,
): Promise<SymbolKlineSeries[]> {
  if (refs.length === 0) {
    return [];
  }
  const base = getBackendBaseURL();
  const params = new URLSearchParams({
    symbols: refs.map(marketRef).join(","),
    limit: String(limit),
  });
  const res = await fetch(`${base}/api/v1/market/klines?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to load daily klines: ${res.status}`);
  }
  return (await res.json()) as SymbolKlineSeries[];
}

export async function loadIntraday(
  symbol: string,
  market = "",
): Promise<IntradaySeries> {
  const base = getBackendBaseURL();
  const params = new URLSearchParams();
  if (market.trim()) {
    params.set("market", market.trim());
  }
  const query = params.size > 0 ? `?${params}` : "";
  const res = await fetch(
    `${base}/api/v1/market/intraday/${encodeURIComponent(symbol)}${query}`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`Failed to load intraday series: ${res.status}`);
  }
  return (await res.json()) as IntradaySeries;
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

export type LoadMarketSectorsOptions = {
  type?: "concept" | "industry";
  sort?: MarketSectorSort;
  keyword?: string;
  limit?: number;
};

export async function loadMarketSectors({
  type = "concept",
  sort = "heat",
  keyword = "",
  limit = 100,
}: LoadMarketSectorsOptions = {}): Promise<MarketSector[]> {
  const base = getBackendBaseURL();
  const params = new URLSearchParams({
    type,
    sort,
    limit: String(limit),
  });
  if (keyword.trim()) {
    params.set("keyword", keyword.trim());
  }
  const res = await fetch(`${base}/api/v1/market/sectors?${params}`);
  if (!res.ok) {
    throw new Error(`Failed to load market sectors: ${res.status}`);
  }
  const items = (await res.json()) as MarketSectorWire[];
  return items.map(normalizeMarketSector);
}

export async function loadMarketSectorDetail(
  sectorId: string,
  memberLimit = 100,
): Promise<MarketSectorDetail> {
  const base = getBackendBaseURL();
  const params = new URLSearchParams({
    member_limit: String(memberLimit),
  });
  const res = await fetch(
    `${base}/api/v1/market/sectors/${encodeURIComponent(sectorId)}?${params}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load market sector detail: ${res.status}`);
  }
  const item = (await res.json()) as MarketSectorDetailWire;
  return {
    ...normalizeMarketSector(item),
    members: item.members.map(normalizeMarketSectorMember),
  };
}

type DefaultWatchlistItemsOptions = {
  includeQuotes?: boolean;
};

function normalizeWatchlistItem(
  item: WatchlistItemWithQuote,
): WatchlistItemWithQuote {
  return {
    ...item,
    instrument: normalizeMarketStatFields(item.instrument),
    quote: item.quote ? normalizeMarketStatFields(item.quote) : null,
  };
}

export async function loadDefaultWatchlistItems({
  includeQuotes = false,
}: DefaultWatchlistItemsOptions = {}): Promise<WatchlistItemWithQuote[]> {
  const params = new URLSearchParams();
  if (includeQuotes) {
    params.set("include_quotes", "true");
  }
  const query = params.size > 0 ? `?${params}` : "";
  const res = await fetch(`/api/market/watchlists/default/items${query}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to load watchlist: ${res.status}`);
  }
  const items = (await res.json()) as WatchlistItemWithQuote[];
  return items.map(normalizeWatchlistItem);
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

export async function removeDefaultWatchlistItem(
  stock: Pick<StockSearchItem, "market" | "symbol">,
): Promise<void> {
  const params = new URLSearchParams({
    market: stock.market,
  });
  const res = await fetch(
    `/api/market/watchlists/default/items/${encodeURIComponent(stock.symbol)}?${params}`,
    {
      method: "DELETE",
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to remove watchlist item: ${res.status}`);
  }
}
