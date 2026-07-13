// Wire shapes returned by apextran-app's market module. These mirror the
// pydantic models in services/app/.../market/domain/models.py — keep in sync.

export interface HotItem {
  rank: number;
  symbol: string;
  name: string;
  boards: number;
  change_pct: number;
  reason: string;
  concept: string;
  hot_score: number;
  latest_price: number | null;
  eastmoney_rank: number | null;
  tonghuashun_rank: number | null;
  kai_pan_la_rank: number | null;
  tao_gu_ba_rank: number | null;
  sources: string[];
  updated_at: string; // ISO 8601
}

export interface StockSearchItem {
  symbol: string;
  name: string;
  market: string;
  latest_price: number | null;
  change_pct: number | null;
  turnover_rate: number | null;
  amount: number | null;
  float_market_cap: number | null;
  total_market_cap: number | null;
  concept: string;
  source: string;
  updated_at: string; // ISO 8601
}

export interface StockQuoteItem {
  symbol: string;
  market: string;
  latest_price: number | null;
  change_pct: number | null;
  turnover_rate: number | null;
  amount: number | null;
  float_market_cap: number | null;
  total_market_cap: number | null;
  source: string;
  updated_at: string; // ISO 8601
}

export interface KlineBar {
  date: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number; // 手 (100 shares)
}

export interface IntradayPoint {
  time: string; // HH:MM, exchange local time
  price: number;
  avg_price: number | null;
}

export interface IntradaySeries {
  symbol: string;
  date: string; // YYYY-MM-DD
  prev_close: number | null;
  points: IntradayPoint[];
  updated_at: string; // ISO 8601
}

export interface Watchlist {
  id: string;
  name: string;
  is_default: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItem {
  id: string;
  instrument: StockSearchItem;
  sort_order: number;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItemWithQuote extends WatchlistItem {
  quote: StockQuoteItem | null;
}

export interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  tags: string[];
  symbols: string[];
  sentiment: number | null;
  heat: number | null;
  views: number | null;
  published_at: string | null; // ISO 8601; null when the source carries no time
}

export type FlashLevel = "normal" | "important";

export interface FlashItem {
  id: string;
  content: string;
  title: string;
  source: string; // publisher, e.g. 财联社 / 华尔街见闻
  url: string;
  level: FlashLevel;
  symbols: string[];
  published_at: string; // ISO 8601
}
