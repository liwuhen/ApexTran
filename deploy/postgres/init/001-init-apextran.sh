#!/usr/bin/env bash
set -Eeuo pipefail

database="${POSTGRES_DB:-apextran}"
migrator="${POSTGRES_USER:-apextran_migrator}"
auth_user="${APEXTRAN_AUTH_DB_USER:-auth_app}"
auth_password="${APEXTRAN_AUTH_DB_PASSWORD:?APEXTRAN_AUTH_DB_PASSWORD is required}"
market_user="${APEXTRAN_MARKET_DB_USER:-market_app}"
market_password="${APEXTRAN_MARKET_DB_PASSWORD:?APEXTRAN_MARKET_DB_PASSWORD is required}"
agent_user="${APEXTRAN_AGENT_DB_USER:-agent_app}"
agent_password="${APEXTRAN_AGENT_DB_PASSWORD:?APEXTRAN_AGENT_DB_PASSWORD is required}"

quote_literal() {
    local value="${1//\'/\'\'}"
    printf "'%s'" "${value}"
}

create_or_update_role() {
    local role="$1"
    local password="$2"
    local role_literal
    local password_literal
    role_literal="$(quote_literal "${role}")"
    password_literal="$(quote_literal "${password}")"

    psql -v ON_ERROR_STOP=1 --username "${migrator}" --dbname "${database}" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = ${role_literal}) THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', ${role_literal}, ${password_literal});
  ELSE
    EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', ${role_literal}, ${password_literal});
  END IF;
END
\$\$;
SQL
}

create_or_update_role "${auth_user}" "${auth_password}"
create_or_update_role "${market_user}" "${market_password}"
create_or_update_role "${agent_user}" "${agent_password}"

auth_user_literal="$(quote_literal "${auth_user}")"
market_user_literal="$(quote_literal "${market_user}")"
agent_user_literal="$(quote_literal "${agent_user}")"
database_literal="$(quote_literal "${database}")"

psql -v ON_ERROR_STOP=1 --username "${migrator}" --dbname "${database}" <<SQL
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS agent;

DO \$\$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', ${database_literal}, ${auth_user_literal});
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', ${database_literal}, ${market_user_literal});
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', ${database_literal}, ${agent_user_literal});
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO %I', ${database_literal}, ${market_user_literal});

  EXECUTE format('GRANT USAGE, CREATE ON SCHEMA auth TO %I', ${auth_user_literal});
  EXECUTE format('GRANT USAGE ON SCHEMA market TO %I', ${market_user_literal});
  EXECUTE format('GRANT USAGE, CREATE ON SCHEMA agent TO %I', ${agent_user_literal});

  EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = auth, public', ${auth_user_literal}, ${database_literal});
  EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = market, public', ${market_user_literal}, ${database_literal});
  EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path = agent, public', ${agent_user_literal}, ${database_literal});
END
\$\$;
SQL
