CREATE TABLE IF NOT EXISTS market.stock_hotlist_snapshots (
  rank INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  boards INTEGER NOT NULL DEFAULT 0,
  change_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  concept TEXT NOT NULL DEFAULT '',
  hot_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  latest_price DOUBLE PRECISION,
  eastmoney_rank INTEGER,
  tonghuashun_rank INTEGER,
  kai_pan_la_rank INTEGER,
  tao_gu_ba_rank INTEGER,
  sources TEXT[] NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_hotlist_snapshots_rank
  ON market.stock_hotlist_snapshots (rank, symbol);

CREATE TABLE IF NOT EXISTS market.stock_quote_snapshots (
  market TEXT NOT NULL DEFAULT '深市A股',
  symbol TEXT NOT NULL,
  latest_price DOUBLE PRECISION,
  change_pct DOUBLE PRECISION,
  source TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (market, symbol)
);

CREATE TABLE IF NOT EXISTS market.stock_daily_klines (
  market TEXT NOT NULL DEFAULT '深市A股',
  symbol TEXT NOT NULL,
  trade_date DATE NOT NULL,
  open DOUBLE PRECISION NOT NULL,
  high DOUBLE PRECISION NOT NULL,
  low DOUBLE PRECISION NOT NULL,
  close DOUBLE PRECISION NOT NULL,
  volume DOUBLE PRECISION NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (market, symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_klines_symbol_date
  ON market.stock_daily_klines (market, symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS market.stock_intraday_series (
  market TEXT NOT NULL DEFAULT '深市A股',
  symbol TEXT NOT NULL,
  trade_date DATE NOT NULL,
  prev_close DOUBLE PRECISION,
  source TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (market, symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_stock_intraday_series_symbol_date
  ON market.stock_intraday_series (market, symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS market.stock_intraday_points (
  market TEXT NOT NULL DEFAULT '深市A股',
  symbol TEXT NOT NULL,
  trade_date DATE NOT NULL,
  minute_time TEXT NOT NULL,
  price DOUBLE PRECISION NOT NULL,
  avg_price DOUBLE PRECISION,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (market, symbol, trade_date, minute_time),
  FOREIGN KEY (market, symbol, trade_date)
    REFERENCES market.stock_intraday_series (market, symbol, trade_date)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stock_intraday_points_symbol_time
  ON market.stock_intraday_points (market, symbol, trade_date DESC, minute_time);

CREATE TABLE IF NOT EXISTS market.stock_snapshot_interests (
  market TEXT NOT NULL DEFAULT '深市A股',
  symbol TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT 'recent_chart',
  last_requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (market, symbol, reason)
);

CREATE INDEX IF NOT EXISTS idx_stock_snapshot_interests_requested
  ON market.stock_snapshot_interests (last_requested_at DESC);

ALTER TABLE market.stock_intraday_points
  DROP CONSTRAINT IF EXISTS stock_intraday_points_market_symbol_trade_date_fkey;

ALTER TABLE market.stock_intraday_points
  ADD CONSTRAINT stock_intraday_points_market_symbol_trade_date_fkey
  FOREIGN KEY (market, symbol, trade_date)
  REFERENCES market.stock_intraday_series (market, symbol, trade_date)
  ON UPDATE CASCADE
  ON DELETE CASCADE;

CREATE TEMP TABLE IF NOT EXISTS tmp_market_snapshot_market_migration (
  old_market TEXT NOT NULL,
  new_market TEXT NOT NULL,
  symbol TEXT NOT NULL
);

TRUNCATE tmp_market_snapshot_market_migration;

INSERT INTO tmp_market_snapshot_market_migration (old_market, new_market, symbol)
SELECT DISTINCT
  old_market,
  CASE
    WHEN symbol LIKE '6%' THEN '沪市A股'
    WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
    WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
    ELSE '深市A股'
  END,
  symbol
FROM (
  SELECT market AS old_market, symbol FROM market.stock_quote_snapshots WHERE market IN ('A_SHARE', 'A股', '')
  UNION
  SELECT market AS old_market, symbol FROM market.stock_daily_klines WHERE market IN ('A_SHARE', 'A股', '')
  UNION
  SELECT market AS old_market, symbol FROM market.stock_intraday_series WHERE market IN ('A_SHARE', 'A股', '')
  UNION
  SELECT market AS old_market, symbol FROM market.stock_intraday_points WHERE market IN ('A_SHARE', 'A股', '')
  UNION
  SELECT market AS old_market, symbol FROM market.stock_snapshot_interests WHERE market IN ('A_SHARE', 'A股', '')
) AS old_snapshots;

INSERT INTO market.stock_quote_snapshots (
  market,
  symbol,
  latest_price,
  change_pct,
  source,
  updated_at,
  created_at
)
SELECT
  migration.new_market,
  quote.symbol,
  quote.latest_price,
  quote.change_pct,
  quote.source,
  quote.updated_at,
  quote.created_at
FROM market.stock_quote_snapshots AS quote
JOIN tmp_market_snapshot_market_migration AS migration
  ON migration.old_market = quote.market
 AND migration.symbol = quote.symbol
WHERE quote.market IN ('A_SHARE', 'A股', '')
ON CONFLICT (market, symbol) DO NOTHING;

DELETE FROM market.stock_quote_snapshots AS quote
USING tmp_market_snapshot_market_migration AS migration
WHERE quote.market = migration.old_market
  AND quote.symbol = migration.symbol;

INSERT INTO market.stock_daily_klines (
  market,
  symbol,
  trade_date,
  open,
  high,
  low,
  close,
  volume,
  source,
  updated_at,
  created_at
)
SELECT
  migration.new_market,
  daily.symbol,
  daily.trade_date,
  daily.open,
  daily.high,
  daily.low,
  daily.close,
  daily.volume,
  daily.source,
  daily.updated_at,
  daily.created_at
FROM market.stock_daily_klines AS daily
JOIN tmp_market_snapshot_market_migration AS migration
  ON migration.old_market = daily.market
 AND migration.symbol = daily.symbol
WHERE daily.market IN ('A_SHARE', 'A股', '')
ON CONFLICT (market, symbol, trade_date) DO NOTHING;

DELETE FROM market.stock_daily_klines AS daily
USING tmp_market_snapshot_market_migration AS migration
WHERE daily.market = migration.old_market
  AND daily.symbol = migration.symbol;

INSERT INTO market.stock_intraday_series (
  market,
  symbol,
  trade_date,
  prev_close,
  source,
  updated_at,
  created_at
)
SELECT
  migration.new_market,
  series.symbol,
  series.trade_date,
  series.prev_close,
  series.source,
  series.updated_at,
  series.created_at
FROM market.stock_intraday_series AS series
JOIN tmp_market_snapshot_market_migration AS migration
  ON migration.old_market = series.market
 AND migration.symbol = series.symbol
WHERE series.market IN ('A_SHARE', 'A股', '')
ON CONFLICT (market, symbol, trade_date) DO NOTHING;

INSERT INTO market.stock_intraday_points (
  market,
  symbol,
  trade_date,
  minute_time,
  price,
  avg_price,
  updated_at,
  created_at
)
SELECT
  migration.new_market,
  point.symbol,
  point.trade_date,
  point.minute_time,
  point.price,
  point.avg_price,
  point.updated_at,
  point.created_at
FROM market.stock_intraday_points AS point
JOIN tmp_market_snapshot_market_migration AS migration
  ON migration.old_market = point.market
 AND migration.symbol = point.symbol
WHERE point.market IN ('A_SHARE', 'A股', '')
ON CONFLICT (market, symbol, trade_date, minute_time) DO NOTHING;

DELETE FROM market.stock_intraday_points AS point
USING tmp_market_snapshot_market_migration AS migration
WHERE point.market = migration.old_market
  AND point.symbol = migration.symbol;

DELETE FROM market.stock_intraday_series AS series
USING tmp_market_snapshot_market_migration AS migration
WHERE series.market = migration.old_market
  AND series.symbol = migration.symbol;

INSERT INTO market.stock_snapshot_interests (
  market,
  symbol,
  reason,
  last_requested_at,
  updated_at
)
SELECT
  migration.new_market,
  interest.symbol,
  interest.reason,
  interest.last_requested_at,
  interest.updated_at
FROM market.stock_snapshot_interests AS interest
JOIN tmp_market_snapshot_market_migration AS migration
  ON migration.old_market = interest.market
 AND migration.symbol = interest.symbol
WHERE interest.market IN ('A_SHARE', 'A股', '')
ON CONFLICT (market, symbol, reason) DO NOTHING;

DELETE FROM market.stock_snapshot_interests AS interest
USING tmp_market_snapshot_market_migration AS migration
WHERE interest.market = migration.old_market
  AND interest.symbol = migration.symbol;

WITH watchlist_market_rows AS (
  SELECT
    id,
    market,
    row_number() OVER (
      PARTITION BY user_id, watchlist_id, symbol, CASE
        WHEN symbol LIKE '6%' THEN '沪市A股'
        WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
        WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
        ELSE '深市A股'
      END
      ORDER BY
        CASE WHEN market IN ('A_SHARE', 'A股', '') THEN 1 ELSE 0 END,
        updated_at DESC,
        created_at DESC,
        id
    ) AS keep_rank
  FROM market.watchlist_items
  WHERE market IN ('A_SHARE', 'A股', '')
     OR market = CASE
       WHEN symbol LIKE '6%' THEN '沪市A股'
       WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
       WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
       ELSE '深市A股'
     END
)
DELETE FROM market.watchlist_items AS item
USING watchlist_market_rows AS ranked
WHERE item.id = ranked.id
  AND ranked.market IN ('A_SHARE', 'A股', '')
  AND ranked.keep_rank > 1;

UPDATE market.watchlist_items
SET market = CASE
    WHEN symbol LIKE '6%' THEN '沪市A股'
    WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
    WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
    ELSE '深市A股'
  END,
  updated_at = now()
WHERE market IN ('A_SHARE', 'A股', '');

WITH stock_market_rows AS (
  SELECT
    id,
    market,
    row_number() OVER (
      PARTITION BY symbol, CASE
        WHEN symbol LIKE '6%' THEN '沪市A股'
        WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
        WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
        ELSE '深市A股'
      END
      ORDER BY
        CASE WHEN market IN ('A_SHARE', 'A股', '') THEN 1 ELSE 0 END,
        updated_at DESC,
        created_at DESC,
        id
    ) AS keep_rank
  FROM market.stock_instruments
  WHERE market IN ('A_SHARE', 'A股', '')
     OR market = CASE
       WHEN symbol LIKE '6%' THEN '沪市A股'
       WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
       WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
       ELSE '深市A股'
     END
)
DELETE FROM market.stock_instruments AS stock
USING stock_market_rows AS ranked
WHERE stock.id = ranked.id
  AND ranked.market IN ('A_SHARE', 'A股', '')
  AND ranked.keep_rank > 1;

UPDATE market.stock_instruments
SET market = CASE
    WHEN symbol LIKE '6%' THEN '沪市A股'
    WHEN symbol LIKE '0%' OR symbol LIKE '3%' THEN '深市A股'
    WHEN symbol LIKE '4%' OR symbol LIKE '8%' OR symbol LIKE '92%' THEN '北交所'
    ELSE '深市A股'
  END,
  exchange = CASE
    WHEN symbol LIKE '60%' OR symbol LIKE '68%' OR symbol LIKE '90%' THEN 'SSE'
    WHEN symbol LIKE '00%' OR symbol LIKE '30%' OR symbol LIKE '20%' THEN 'SZSE'
    WHEN symbol LIKE '43%' OR symbol LIKE '83%' OR symbol LIKE '87%' OR symbol LIKE '88%' THEN 'BSE'
    ELSE exchange
  END,
  updated_at = now()
WHERE market IN ('A_SHARE', 'A股', '');

ALTER TABLE market.stock_quote_snapshots
  ALTER COLUMN market SET DEFAULT '深市A股';

ALTER TABLE market.stock_daily_klines
  ALTER COLUMN market SET DEFAULT '深市A股';

ALTER TABLE market.stock_intraday_series
  ALTER COLUMN market SET DEFAULT '深市A股';

ALTER TABLE market.stock_intraday_points
  ALTER COLUMN market SET DEFAULT '深市A股';

ALTER TABLE market.stock_snapshot_interests
  ALTER COLUMN market SET DEFAULT '深市A股';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'market_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA market TO market_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA market
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO market_app;
  END IF;
END
$$;
