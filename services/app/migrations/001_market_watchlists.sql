CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS market;

CREATE TABLE IF NOT EXISTS market.stock_instruments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL,
  market TEXT NOT NULL DEFAULT '',
  exchange TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  pinyin TEXT NOT NULL DEFAULT '',
  pinyin_abbr TEXT NOT NULL DEFAULT '',
  industry TEXT NOT NULL DEFAULT '',
  concept TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  listed_at DATE,
  delisted_at DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_instruments_symbol
  ON market.stock_instruments (symbol);

CREATE INDEX IF NOT EXISTS idx_stock_instruments_market_symbol
  ON market.stock_instruments (market, symbol);

CREATE INDEX IF NOT EXISTS idx_stock_instruments_name_trgm
  ON market.stock_instruments USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_stock_instruments_pinyin_trgm
  ON market.stock_instruments USING gin (pinyin gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_stock_instruments_pinyin_abbr_trgm
  ON market.stock_instruments USING gin (pinyin_abbr gin_trgm_ops);

CREATE TABLE IF NOT EXISTS market.watchlists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  is_default BOOLEAN NOT NULL DEFAULT false,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (user_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlists_one_default
  ON market.watchlists (user_id)
  WHERE is_default = true;

CREATE INDEX IF NOT EXISTS idx_watchlists_user_order
  ON market.watchlists (user_id, sort_order, created_at);

-- User-owned identity and ordering only. Realtime quote fields stay in short
-- cache and are joined by the API/frontend at read time.
CREATE TABLE IF NOT EXISTS market.watchlist_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  watchlist_id UUID NOT NULL REFERENCES market.watchlists(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  market TEXT NOT NULL DEFAULT '',
  concept TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  stock_updated_at TIMESTAMPTZ NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (user_id, watchlist_id, market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_items_user
  ON market.watchlist_items (user_id);

CREATE INDEX IF NOT EXISTS idx_watchlist_items_watchlist_order
  ON market.watchlist_items (watchlist_id, sort_order, created_at);

CREATE INDEX IF NOT EXISTS idx_watchlist_items_symbol
  ON market.watchlist_items (market, symbol);

ALTER TABLE market.watchlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE market.watchlist_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE market.watchlists FORCE ROW LEVEL SECURITY;
ALTER TABLE market.watchlist_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS watchlists_user_isolation ON market.watchlists;
CREATE POLICY watchlists_user_isolation
  ON market.watchlists
  USING (user_id = current_setting('app.user_id', true))
  WITH CHECK (user_id = current_setting('app.user_id', true));

DROP POLICY IF EXISTS watchlist_items_user_isolation ON market.watchlist_items;
CREATE POLICY watchlist_items_user_isolation
  ON market.watchlist_items
  USING (user_id = current_setting('app.user_id', true))
  WITH CHECK (user_id = current_setting('app.user_id', true));
