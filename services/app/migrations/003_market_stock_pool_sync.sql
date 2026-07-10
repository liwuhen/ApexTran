DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'market_app') THEN
    EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO market_app', current_database());
  END IF;
END
$$;
