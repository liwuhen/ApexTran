#!/usr/bin/env bash
#
# Start the full ApexTran stack behind a local Nginx reverse proxy.
#
# Full topology (dev 与 prod 一致,都起量产全功能):
#   Nginx :80 -> frontend      127.0.0.1:3000   (Next.js)
#             -> backend/agent  127.0.0.1:8000   (/api/langgraph, /api/models…)
#             -> app  /api/v1/* 127.0.0.1:8100   (apextran-app serve:行情 + 分析)
#             -> centrifugo /connection/ 127.0.0.1:8400 (实时推送)
#   app-worker (采集 + leader)  ── 后台进程,无端口
#   redis 127.0.0.1:6379 · centrifugo :8400  ── docker 起(见 APEXTRAN_APP_INFRA)
#
# 业务服务量产开关(可用环境变量覆盖,dev 亦默认全开):
#   APEXTRAN_APP_INFRA=auto|docker|none   # redis+centrifugo:auto=有 docker 就全开
#   APP_MARKET_SOURCE=akshare|mock        # 默认真数据 akshare
#   APP_AGENT_CLIENT=http|local           # 默认真调 agent-service /analyze
#
# Commands:
#   scripts/start_nginx_stack.sh start      # 按 APEXTRAN_FRONTEND_MODE(默认 prod)启动
#   scripts/start_nginx_stack.sh dev        # 开发模式(next dev + HMR + 仅开发生效的 auth 配置)
#   scripts/start_nginx_stack.sh prod       # 生产模式(next build + next start)
#   scripts/start_nginx_stack.sh stop
#   scripts/start_nginx_stack.sh restart
#   scripts/start_nginx_stack.sh status
#   scripts/start_nginx_stack.sh logs
#   scripts/start_nginx_stack.sh foreground

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT_APP_ENVIRONMENT_SET=0
if [[ -v APP_ENVIRONMENT ]]; then
    PARENT_APP_ENVIRONMENT_SET=1
fi

load_env_file() {
    if [[ "${APEXTRAN_LOAD_ENV:-1}" == "0" ]]; then
        return
    fi

    local env_file="${APEXTRAN_ENV_FILE:-${ROOT_DIR}/.env}"
    [[ -f "${env_file}" ]] || return

    local line key value
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        [[ -z "${line}" || "${line}" == \#* ]] && continue
        if [[ "${line}" == export[[:space:]]* ]]; then
            line="${line#export}"
            line="${line#"${line%%[![:space:]]*}"}"
        fi
        [[ "${line}" == *=* ]] || continue

        key="${line%%=*}"
        key="${key%"${key##*[![:space:]]}"}"
        value="${line#*=}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

        # Shell-provided values win over .env. This keeps one clear precedence:
        # explicit environment > .env > script runtime defaults.
        if [[ -v "${key}" ]]; then
            continue
        fi

        if [[ "${value}" == \"* ]]; then
            value="${value#\"}"
            value="${value%%\"*}"
        elif [[ "${value}" == \'* ]]; then
            value="${value#\'}"
            value="${value%%\'*}"
        else
            if [[ "${value}" =~ ^(.*)[[:space:]]+#.*$ ]]; then
                value="${BASH_REMATCH[1]}"
            fi
            value="${value%"${value##*[![:space:]]}"}"
        fi
        if [[ "${value}" == "~/"* ]]; then
            value="${HOME}${value:1}"
        fi
        export "${key}=${value}"
    done <"${env_file}"

    APEXTRAN_ENV_FILE_LOADED="${env_file}"
}

load_env_file

FRONTEND_DIR="${ROOT_DIR}/frontend"
RUN_DIR="${APEXTRAN_RUN_DIR:-${ROOT_DIR}/.run}"
LOG_DIR="${APEXTRAN_LOG_DIR:-${RUN_DIR}/logs}"

FRONTEND_HOST="${APEXTRAN_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${APEXTRAN_FRONTEND_PORT:-3000}"
BACKEND_HOST="${ApexTran_WEB_HOST:-127.0.0.1}"
BACKEND_PORT="${ApexTran_WEB_PORT:-8000}"
PUBLIC_BASE_URL="${APEXTRAN_PUBLIC_BASE_URL:-http://127.0.0.1}"
FRONTEND_MODE="${APEXTRAN_FRONTEND_MODE:-prod}"
WAIT_SECONDS="${APEXTRAN_WAIT_SECONDS:-45}"
SKIP_NGINX="${APEXTRAN_SKIP_NGINX:-0}"

BACKEND_PID="${RUN_DIR}/backend-web.pid"
FRONTEND_PID="${RUN_DIR}/frontend.pid"
BACKEND_LOG="${LOG_DIR}/backend-web.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"

# --- Business microservice (apextran-app) + its infra --------------------------
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8100}"
APP_API_PID="${RUN_DIR}/app-api.pid"
APP_WORKER_PID="${RUN_DIR}/app-worker.pid"
APP_API_LOG="${LOG_DIR}/app-api.log"
APP_WORKER_LOG="${LOG_DIR}/app-worker.log"

# 量产默认:真数据 + 真 agent + Redis 共享缓存 + Centrifugo 实时(dev/prod 一致)。
APP_INFRA="${APEXTRAN_APP_INFRA:-auto}"                 # auto | docker | none
APP_MARKET_SOURCE="${APP_MARKET_SOURCE:-akshare}"       # akshare | mock
APP_AGENT_CLIENT="${APP_AGENT_CLIENT:-http}"            # http | local
REDIS_CONTAINER="${APEXTRAN_REDIS_CONTAINER:-apextran-redis}"
REDIS_PORT="${APEXTRAN_REDIS_PORT:-6380}"
CENTRIFUGO_CONTAINER="${APEXTRAN_CENTRIFUGO_CONTAINER:-apextran-centrifugo}"
CENTRIFUGO_PORT="${APEXTRAN_CENTRIFUGO_PORT:-8400}"

# Resolved by resolve_app_infra().
USE_DOCKER_INFRA=0
APP_CACHE_BACKEND="${APP_CACHE_BACKEND:-}"
APP_REDIS_URL="${APP_REDIS_URL:-}"
APP_CENTRIFUGO_API_URL="${APP_CENTRIFUGO_API_URL:-}"
CENTRIFUGO_API_KEY=""
CENTRIFUGO_TOKEN_SECRET=""

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'
    C_CYAN=$'\033[36m'
else
    C_RESET=""
    C_BOLD=""
    C_DIM=""
    C_RED=""
    C_GREEN=""
    C_YELLOW=""
    C_BLUE=""
    C_CYAN=""
fi

log_line() {
    local level="$1"
    local color="$2"
    shift 2
    printf '%s%s[apextran]%s %s%-7s%s %s\n' \
        "${C_BOLD}" "${C_CYAN}" "${C_RESET}" \
        "${color}" "${level}" "${C_RESET}" \
        "$*"
}

log() {
    log_line "INFO" "${C_BLUE}" "$*"
}

ok() {
    log_line "OK" "${C_GREEN}" "$*"
}

warn() {
    log_line "WARN" "${C_YELLOW}" "$*"
}

hint() {
    log_line "HINT" "${C_CYAN}" "$*"
}

error() {
    log_line "ERROR" "${C_RED}" "$*" >&2
}

die() {
    error "$*"
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

pid_alive() {
    local pid_file="$1"
    [[ -s "${pid_file}" ]] || return 1
    local pid
    pid="$(cat "${pid_file}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    kill -0 "${pid}" >/dev/null 2>&1
}

port_in_use() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
        return
    fi
    return 1
}

ensure_port_available() {
    local name="$1"
    local port="$2"
    local pid_file="$3"
    if pid_alive "${pid_file}"; then
        return
    fi
    if port_in_use "${port}"; then
        die "${name} port ${port} is already in use by a process not started by this script"
    fi
}

ensure_secret() {
    if [[ -n "${BETTER_AUTH_SECRET:-}" ]]; then
        export BETTER_AUTH_SECRET
        return
    fi

    local secret_file="${RUN_DIR}/better_auth_secret"
    mkdir -p "${RUN_DIR}"
    if [[ ! -s "${secret_file}" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            openssl rand -hex 32 >"${secret_file}"
        else
            need_cmd python3
            python3 -c 'import secrets; print(secrets.token_hex(32))' >"${secret_file}"
        fi
        chmod 600 "${secret_file}"
    fi
    BETTER_AUTH_SECRET="$(cat "${secret_file}")"
    export BETTER_AUTH_SECRET
}

# 多租户信任模型(量产默认开启,dev 亦然):前后端共享一个代理密钥。自动生成并
# 持久化到 ${RUN_DIR}/web_proxy_secret,使 backend 与 frontend 拿到同一个值——
# 后端据此确认「带身份的请求确实来自受信前端代理」。可用环境变量覆盖。
ensure_proxy_secret() {
    if [[ -n "${ApexTran_WEB_PROXY_SECRET:-}" ]]; then
        export ApexTran_WEB_PROXY_SECRET
        return
    fi

    local secret_file="${RUN_DIR}/web_proxy_secret"
    mkdir -p "${RUN_DIR}"
    if [[ ! -s "${secret_file}" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            openssl rand -hex 32 >"${secret_file}"
        else
            need_cmd python3
            python3 -c 'import secrets; print(secrets.token_hex(32))' >"${secret_file}"
        fi
        chmod 600 "${secret_file}"
    fi
    ApexTran_WEB_PROXY_SECRET="$(cat "${secret_file}")"
    export ApexTran_WEB_PROXY_SECRET
}

ensure_internal_jwt_secret() {
    if [[ -n "${APEXTRAN_INTERNAL_JWT_SECRET:-}" ]]; then
        export APEXTRAN_INTERNAL_JWT_SECRET
        return
    fi

    local secret_file="${RUN_DIR}/internal_jwt_secret"
    mkdir -p "${RUN_DIR}"
    if [[ ! -s "${secret_file}" ]]; then
        if command -v openssl >/dev/null 2>&1; then
            openssl rand -hex 32 >"${secret_file}"
        else
            need_cmd python3
            python3 -c 'import secrets; print(secrets.token_hex(32))' >"${secret_file}"
        fi
        chmod 600 "${secret_file}"
    fi
    APEXTRAN_INTERNAL_JWT_SECRET="$(cat "${secret_file}")"
    export APEXTRAN_INTERNAL_JWT_SECRET
}

wait_for_url() {
    local name="$1"
    local url="$2"
    local seconds="$3"

    if ! command -v curl >/dev/null 2>&1; then
        warn "curl not found; skipping ${name} readiness check"
        return 0
    fi

    for _ in $(seq 1 "${seconds}"); do
        if curl -fsS -o /dev/null "${url}" >/dev/null 2>&1; then
            ok "${name} is ready: ${url}"
            return 0
        fi
        sleep 1
    done
    die "${name} did not become ready within ${seconds}s: ${url}"
}

start_process() {
    local name="$1"
    local pid_file="$2"
    local log_file="$3"
    shift 3

    if pid_alive "${pid_file}"; then
        log "${name} already running with pid $(cat "${pid_file}")"
        return
    fi

    mkdir -p "${RUN_DIR}" "${LOG_DIR}"
    log "starting ${name}"
    log "${C_DIM}log: ${log_file}${C_RESET}"
    (
        cd "${ROOT_DIR}"
        nohup "$@" >"${log_file}" 2>&1 &
        printf '%s\n' "$!" >"${pid_file}"
    )
}

start_process_in_dir() {
    local name="$1"
    local pid_file="$2"
    local log_file="$3"
    local cwd="$4"
    shift 4

    if pid_alive "${pid_file}"; then
        log "${name} already running with pid $(cat "${pid_file}")"
        return
    fi

    mkdir -p "${RUN_DIR}" "${LOG_DIR}"
    log "starting ${name}"
    log "${C_DIM}log: ${log_file}${C_RESET}"
    (
        cd "${cwd}"
        nohup "$@" >"${log_file}" 2>&1 &
        printf '%s\n' "$!" >"${pid_file}"
    )
}

stop_process() {
    local name="$1"
    local pid_file="$2"

    if ! pid_alive "${pid_file}"; then
        warn "${name} is not running"
        rm -f "${pid_file}"
        return
    fi

    local pid
    pid="$(cat "${pid_file}")"
    log "stopping ${name} pid ${pid}"
    kill "${pid}" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
        if ! kill -0 "${pid}" >/dev/null 2>&1; then
            rm -f "${pid_file}"
            return
        fi
        sleep 1
    done
    log "${name} did not stop gracefully; sending SIGKILL"
    kill -9 "${pid}" >/dev/null 2>&1 || true
    rm -f "${pid_file}"
}

install_nginx_config() {
    if [[ "${SKIP_NGINX}" == "1" ]]; then
        warn "APEXTRAN_SKIP_NGINX=1; skipping Nginx install/reload"
        return
    fi

    if [[ "${FRONTEND_PORT}" != "3000" || "${BACKEND_PORT}" != "8000" ]]; then
        die "deploy/nginx/apextran.conf expects frontend 3000 and backend 8000; keep defaults or update the config"
    fi

    if ! command -v nginx >/dev/null 2>&1; then
        warn "nginx not found; services started, but reverse proxy was not installed"
        return
    fi

    local src="${ROOT_DIR}/deploy/nginx/apextran.conf"
    local dest="/etc/nginx/conf.d/apextran.conf"
    log "installing Nginx config to ${dest}"
    if [[ -w "$(dirname "${dest}")" ]]; then
        cp "${src}" "${dest}"
        nginx -t
        reload_nginx
    else
        need_cmd sudo
        sudo cp "${src}" "${dest}"
        sudo nginx -t
        reload_nginx_with_sudo
    fi
}

nginx_install_hint() {
    hint "Install Nginx first, then rerun the command."
    hint "Debian/Ubuntu:       sudo apt-get update && sudo apt-get install -y nginx"
    hint "RHEL/CentOS/Fedora:  sudo dnf install -y nginx"
    hint "macOS Homebrew:      brew install nginx"
    hint "Local without Nginx: APEXTRAN_SKIP_NGINX=1 scripts/start_nginx_stack.sh start"
}

preflight_nginx() {
    if [[ "${SKIP_NGINX}" == "1" ]]; then
        return
    fi
    if command -v nginx >/dev/null 2>&1; then
        return
    fi
    if [[ "${FRONTEND_MODE}" == "prod" ]]; then
        error "nginx is required for production-mode startup"
        nginx_install_hint
        exit 2
    fi
    warn "nginx not found; dev-mode startup will run without reverse proxy"
}

reload_nginx() {
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet nginx; then
            systemctl reload nginx
        else
            systemctl start nginx
        fi
    else
        nginx -s reload || nginx
    fi
}

reload_nginx_with_sudo() {
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet nginx; then
            sudo systemctl reload nginx
        else
            sudo systemctl start nginx
        fi
    else
        sudo nginx -s reload || sudo nginx
    fi
}

start_backend() {
    need_cmd uv
    ensure_port_available "backend" "${BACKEND_PORT}" "${BACKEND_PID}"
    start_process \
        "backend WebChannel" \
        "${BACKEND_PID}" \
        "${BACKEND_LOG}" \
        env ApexTran_WEB_HOST="${BACKEND_HOST}" ApexTran_WEB_PORT="${BACKEND_PORT}" \
            ApexTran_WEB_PROXY_SECRET="${ApexTran_WEB_PROXY_SECRET}" \
            uv run ApexTran web
    wait_for_url "backend" "http://${BACKEND_HOST}:${BACKEND_PORT}/health" "${WAIT_SECONDS}"
}

start_frontend() {
    need_cmd corepack
    ensure_secret
    ensure_port_available "frontend" "${FRONTEND_PORT}" "${FRONTEND_PID}"

    if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
        log "installing frontend dependencies"
        (cd "${FRONTEND_DIR}" && corepack pnpm install --frozen-lockfile)
    fi

    case "${FRONTEND_MODE}" in
        prod)
            if [[ "${APEXTRAN_REBUILD_FRONTEND:-0}" == "1" || ! -s "${FRONTEND_DIR}/.next/BUILD_ID" ]]; then
                log "building frontend"
                (
                    cd "${FRONTEND_DIR}"
                    BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET}" \
                    BETTER_AUTH_URL="${BETTER_AUTH_URL:-${BETTER_AUTH_BASE_URL:-${PUBLIC_BASE_URL}}}" \
                    BETTER_AUTH_DATABASE_URL="${BETTER_AUTH_DATABASE_URL:-}" \
                    AUTH_DATABASE_URL="${AUTH_DATABASE_URL:-}" \
                    APEXTRAN_INTERNAL_JWT_SECRET="${APEXTRAN_INTERNAL_JWT_SECRET}" \
                    APEXTRAN_INTERNAL_JWT_ISSUER="${APEXTRAN_INTERNAL_JWT_ISSUER:-apextran-bff}" \
                    APEXTRAN_INTERNAL_JWT_AUDIENCE="${APEXTRAN_INTERNAL_JWT_AUDIENCE:-apextran-app}" \
                    corepack pnpm build
                )
            fi
            start_process_in_dir \
                "frontend" \
                "${FRONTEND_PID}" \
                "${FRONTEND_LOG}" \
                "${FRONTEND_DIR}" \
                env BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET}" \
                    BETTER_AUTH_URL="${BETTER_AUTH_URL:-${BETTER_AUTH_BASE_URL:-${PUBLIC_BASE_URL}}}" \
                    BETTER_AUTH_DATABASE_URL="${BETTER_AUTH_DATABASE_URL:-}" \
                    AUTH_DATABASE_URL="${AUTH_DATABASE_URL:-}" \
                    ApexTran_WEB_PROXY_SECRET="${ApexTran_WEB_PROXY_SECRET}" \
                    APEXTRAN_INTERNAL_JWT_SECRET="${APEXTRAN_INTERNAL_JWT_SECRET}" \
                    APEXTRAN_INTERNAL_JWT_ISSUER="${APEXTRAN_INTERNAL_JWT_ISSUER:-apextran-bff}" \
                    APEXTRAN_INTERNAL_JWT_AUDIENCE="${APEXTRAN_INTERNAL_JWT_AUDIENCE:-apextran-app}" \
                    APEXTRAN_REQUIRE_AUTH="${APEXTRAN_REQUIRE_AUTH:-1}" \
                    corepack pnpm exec next start --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
            ;;
        dev)
            # APEXTRAN_DEV=1 让 better-auth 启用仅开发生效的本地可信来源;
            # BETTER_AUTH_URL 指向本地 dev 地址(better-auth 只读这个变量,不读 BASE_URL)。
            # 量产信任模型默认开启:密钥闸门 + 强制鉴权(dev 亦然,可用环境变量覆盖)。
            start_process_in_dir \
                "frontend" \
                "${FRONTEND_PID}" \
                "${FRONTEND_LOG}" \
                "${FRONTEND_DIR}" \
                env APEXTRAN_DEV=1 \
                    BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET}" \
                    BETTER_AUTH_URL="${BETTER_AUTH_URL:-http://localhost:${FRONTEND_PORT}}" \
                    BETTER_AUTH_DATABASE_URL="${BETTER_AUTH_DATABASE_URL:-}" \
                    AUTH_DATABASE_URL="${AUTH_DATABASE_URL:-}" \
                    ApexTran_WEB_PROXY_SECRET="${ApexTran_WEB_PROXY_SECRET}" \
                    APEXTRAN_INTERNAL_JWT_SECRET="${APEXTRAN_INTERNAL_JWT_SECRET}" \
                    APEXTRAN_INTERNAL_JWT_ISSUER="${APEXTRAN_INTERNAL_JWT_ISSUER:-apextran-bff}" \
                    APEXTRAN_INTERNAL_JWT_AUDIENCE="${APEXTRAN_INTERNAL_JWT_AUDIENCE:-apextran-app}" \
                    APEXTRAN_REQUIRE_AUTH="${APEXTRAN_REQUIRE_AUTH:-1}" \
                    corepack pnpm exec next dev --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --webpack
            ;;
        *)
            die "unknown APEXTRAN_FRONTEND_MODE=${FRONTEND_MODE}; expected prod or dev"
            ;;
    esac

    wait_for_url "frontend" "http://${FRONTEND_HOST}:${FRONTEND_PORT}/" "${WAIT_SECONDS}"
}

resolve_app_infra() {
    case "${APP_INFRA}" in
        none)
            USE_DOCKER_INFRA=0
            ;;
        docker)
            command -v docker >/dev/null 2>&1 || die "APEXTRAN_APP_INFRA=docker but docker not found"
            docker info >/dev/null 2>&1 || die "APEXTRAN_APP_INFRA=docker but docker daemon is not reachable"
            USE_DOCKER_INFRA=1
            ;;
        auto)
            if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
                USE_DOCKER_INFRA=1
            else
                warn "docker 不可用;业务服务降级为内存缓存 + 无实时推送(akshare 真数据仍可用)"
                warn "要跑量产全功能请装 docker,或 APEXTRAN_APP_INFRA=docker 强制。"
                USE_DOCKER_INFRA=0
            fi
            ;;
        *)
            die "unknown APEXTRAN_APP_INFRA=${APP_INFRA}; expected auto|docker|none"
            ;;
    esac

    if [[ "${USE_DOCKER_INFRA}" == "1" ]]; then
        APP_CACHE_BACKEND="${APP_CACHE_BACKEND:-redis}"
        APP_REDIS_URL="${APP_REDIS_URL:-redis://127.0.0.1:${REDIS_PORT}/0}"
        APP_CENTRIFUGO_API_URL="${APP_CENTRIFUGO_API_URL:-http://127.0.0.1:${CENTRIFUGO_PORT}/api}"
    else
        APP_CACHE_BACKEND="${APP_CACHE_BACKEND:-memory}"
        APP_REDIS_URL="${APP_REDIS_URL:-}"
        APP_CENTRIFUGO_API_URL="${APP_CENTRIFUGO_API_URL:-}"
    fi
}

# Shared Centrifugo secrets (api key + token HMAC), generated once and persisted
# so app-api, the worker, and the Centrifugo container all agree across restarts.
ensure_centrifugo_secrets() {
    local key_file="${RUN_DIR}/centrifugo_api_key"
    local tok_file="${RUN_DIR}/centrifugo_token_secret"
    mkdir -p "${RUN_DIR}"
    local f
    for f in "${key_file}" "${tok_file}"; do
        if [[ ! -s "${f}" ]]; then
            if command -v openssl >/dev/null 2>&1; then
                openssl rand -hex 32 >"${f}"
            else
                need_cmd python3
                python3 -c 'import secrets; print(secrets.token_hex(32))' >"${f}"
            fi
            chmod 600 "${f}"
        fi
    done
    CENTRIFUGO_API_KEY="$(cat "${key_file}")"
    CENTRIFUGO_TOKEN_SECRET="$(cat "${tok_file}")"
}

docker_container_running() {
    [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]
}

start_infra() {
    [[ "${USE_DOCKER_INFRA}" == "1" ]] || return 0
    need_cmd docker
    ensure_centrifugo_secrets

    if docker_container_running "${REDIS_CONTAINER}"; then
        log "redis already running (${REDIS_CONTAINER})"
    else
        docker rm -f "${REDIS_CONTAINER}" >/dev/null 2>&1 || true
        log "starting redis (${REDIS_CONTAINER}) on 127.0.0.1:${REDIS_PORT}"
        docker run -d --name "${REDIS_CONTAINER}" \
            -p "127.0.0.1:${REDIS_PORT}:6379" \
            redis:7-alpine redis-server --save "" --appendonly no >/dev/null
    fi

    if docker_container_running "${CENTRIFUGO_CONTAINER}"; then
        log "centrifugo already running (${CENTRIFUGO_CONTAINER})"
    else
        docker rm -f "${CENTRIFUGO_CONTAINER}" >/dev/null 2>&1 || true
        log "starting centrifugo (${CENTRIFUGO_CONTAINER}) on 127.0.0.1:${CENTRIFUGO_PORT}"
        docker run -d --name "${CENTRIFUGO_CONTAINER}" \
            -p "127.0.0.1:${CENTRIFUGO_PORT}:8000" \
            -e CENTRIFUGO_API_KEY="${CENTRIFUGO_API_KEY}" \
            -e CENTRIFUGO_TOKEN_HMAC_SECRET_KEY="${CENTRIFUGO_TOKEN_SECRET}" \
            -e CENTRIFUGO_ALLOWED_ORIGINS="*" \
            -e CENTRIFUGO_ALLOW_SUBSCRIBE_FOR_ANONYMOUS="true" \
            -e CENTRIFUGO_ALLOW_SUBSCRIBE_FOR_CLIENT="true" \
            -e CENTRIFUGO_HEALTH="true" \
            centrifugo/centrifugo:v5 centrifugo >/dev/null
    fi

    wait_for_url "centrifugo" "http://127.0.0.1:${CENTRIFUGO_PORT}/health" "${WAIT_SECONDS}"
}

stop_infra() {
    command -v docker >/dev/null 2>&1 || return 0
    local c
    for c in "${CENTRIFUGO_CONTAINER}" "${REDIS_CONTAINER}"; do
        if docker inspect "${c}" >/dev/null 2>&1; then
            log "removing container ${c}"
            docker rm -f "${c}" >/dev/null 2>&1 || true
        fi
    done
}

start_app_api() {
    need_cmd uv
    ensure_port_available "app-api" "${APP_PORT}" "${APP_API_PID}"
    local app_environment="${FRONTEND_MODE}"
    if [[ "${PARENT_APP_ENVIRONMENT_SET}" == "1" ]]; then
        app_environment="${APP_ENVIRONMENT}"
    fi
    start_process \
        "app-api (serve)" \
        "${APP_API_PID}" \
        "${APP_API_LOG}" \
        env APP_HOST="${APP_HOST}" APP_PORT="${APP_PORT}" \
            APP_ENVIRONMENT="${app_environment}" \
            APP_CACHE_BACKEND="${APP_CACHE_BACKEND}" \
            APP_REDIS_URL="${APP_REDIS_URL}" \
            APP_DB_URL="${APP_DB_URL:-}" \
            APP_MARKET_SOURCE="${APP_MARKET_SOURCE}" \
            APP_AGENT_CLIENT="${APP_AGENT_CLIENT}" \
            APP_AGENT_BASE_URL="http://${BACKEND_HOST}:${BACKEND_PORT}" \
            APP_PROXY_SECRET="${ApexTran_WEB_PROXY_SECRET}" \
            APP_INTERNAL_JWT_SECRET="${APEXTRAN_INTERNAL_JWT_SECRET}" \
            APP_INTERNAL_JWT_ISSUER="${APEXTRAN_INTERNAL_JWT_ISSUER:-apextran-bff}" \
            APP_INTERNAL_JWT_AUDIENCE="${APEXTRAN_INTERNAL_JWT_AUDIENCE:-apextran-app}" \
            APP_CENTRIFUGO_API_URL="${APP_CENTRIFUGO_API_URL}" \
            APP_CENTRIFUGO_API_KEY="${CENTRIFUGO_API_KEY}" \
            uv run --package apextran-app apextran-app serve
    # /healthz is pure liveness, so a flaky akshare upstream won't block boot.
    wait_for_url "app-api" "http://${APP_HOST}:${APP_PORT}/healthz" "${WAIT_SECONDS}"
}

start_app_worker() {
    need_cmd uv
    local app_environment="${FRONTEND_MODE}"
    if [[ "${PARENT_APP_ENVIRONMENT_SET}" == "1" ]]; then
        app_environment="${APP_ENVIRONMENT}"
    fi
    start_process \
        "app-worker" \
        "${APP_WORKER_PID}" \
        "${APP_WORKER_LOG}" \
        env APP_CACHE_BACKEND="${APP_CACHE_BACKEND}" \
            APP_ENVIRONMENT="${app_environment}" \
            APP_REDIS_URL="${APP_REDIS_URL}" \
            APP_DB_URL="${APP_DB_URL:-}" \
            APP_MARKET_SOURCE="${APP_MARKET_SOURCE}" \
            APP_CENTRIFUGO_API_URL="${APP_CENTRIFUGO_API_URL}" \
            APP_CENTRIFUGO_API_KEY="${CENTRIFUGO_API_KEY}" \
            uv run --package apextran-app apextran-app worker
}

start_stack() {
    if [[ -n "${APEXTRAN_ENV_FILE_LOADED:-}" ]]; then
        log "env file           ${APEXTRAN_ENV_FILE_LOADED}"
    else
        warn "env file           not loaded (set APEXTRAN_ENV_FILE or create ${ROOT_DIR}/.env)"
    fi
    preflight_nginx
    ensure_proxy_secret
    ensure_internal_jwt_secret
    resolve_app_infra
    start_infra
    start_backend
    start_app_api
    start_app_worker
    start_frontend
    install_nginx_config
    if [[ "${SKIP_NGINX}" != "1" ]] && command -v curl >/dev/null 2>&1 && command -v nginx >/dev/null 2>&1; then
        wait_for_url "nginx" "http://127.0.0.1/nginx-health" 10
    fi
    ok "stack is ready"
    log "public entry       ${PUBLIC_BASE_URL}"
    log "frontend upstream  http://${FRONTEND_HOST}:${FRONTEND_PORT}"
    log "backend/agent      http://${BACKEND_HOST}:${BACKEND_PORT}"
    log "app (/api/v1/*)    http://${APP_HOST}:${APP_PORT}  · source=${APP_MARKET_SOURCE} · agent=${APP_AGENT_CLIENT} · cache=${APP_CACHE_BACKEND}"
    if [[ -n "${APP_DB_URL:-}" ]]; then
        log "market db          APP_DB_URL configured"
    else
        warn "market db          APP_DB_URL empty; stock search falls back to live source"
    fi
    if [[ "${USE_DOCKER_INFRA}" == "1" ]]; then
        log "realtime           centrifugo http://127.0.0.1:${CENTRIFUGO_PORT} (/connection/*) · redis :${REDIS_PORT}"
    else
        warn "realtime           关闭(无 docker):内存缓存、无 Centrifugo 推送"
    fi
    log "trust model        proxy-secret ON · require-auth=${APEXTRAN_REQUIRE_AUTH:-1} (未登录将被拒;需先注册/登录)"
}

stop_stack() {
    stop_process "frontend" "${FRONTEND_PID}"
    stop_process "app-worker" "${APP_WORKER_PID}"
    stop_process "app-api (serve)" "${APP_API_PID}"
    stop_process "backend WebChannel" "${BACKEND_PID}"
    stop_infra
}

status_stack() {
    if [[ -n "${APEXTRAN_ENV_FILE_LOADED:-}" ]]; then
        ok "env loaded ${APEXTRAN_ENV_FILE_LOADED}"
    else
        warn "env not loaded"
    fi
    if [[ -n "${APP_DB_URL:-}" ]]; then
        ok "market db configured"
    else
        warn "market db APP_DB_URL empty"
    fi
    if pid_alive "${BACKEND_PID}"; then
        ok "backend/agent running pid $(cat "${BACKEND_PID}")"
    else
        warn "backend/agent stopped"
    fi
    if pid_alive "${APP_API_PID}"; then
        ok "app-api running pid $(cat "${APP_API_PID}")"
    else
        warn "app-api stopped"
    fi
    if pid_alive "${APP_WORKER_PID}"; then
        ok "app-worker running pid $(cat "${APP_WORKER_PID}")"
    else
        warn "app-worker stopped"
    fi
    if pid_alive "${FRONTEND_PID}"; then
        ok "frontend running pid $(cat "${FRONTEND_PID}")"
    else
        warn "frontend stopped"
    fi
    if command -v docker >/dev/null 2>&1; then
        local c
        for c in "${REDIS_CONTAINER}" "${CENTRIFUGO_CONTAINER}"; do
            if docker_container_running "${c}"; then
                ok "${c} running"
            else
                warn "${c} stopped"
            fi
        done
    fi
}

logs_stack() {
    mkdir -p "${LOG_DIR}"
    touch "${BACKEND_LOG}" "${APP_API_LOG}" "${APP_WORKER_LOG}" "${FRONTEND_LOG}"
    tail -n 80 -f "${BACKEND_LOG}" "${APP_API_LOG}" "${APP_WORKER_LOG}" "${FRONTEND_LOG}"
}

foreground_stack() {
    trap 'stop_stack' EXIT
    trap 'stop_stack; exit 130' INT TERM
    start_stack
    ok "foreground monitor started; press Ctrl-C to stop the stack"
    while true; do
        if ! pid_alive "${BACKEND_PID}"; then
            die "backend exited; see ${BACKEND_LOG}"
        fi
        if ! pid_alive "${APP_API_PID}"; then
            die "app-api exited; see ${APP_API_LOG}"
        fi
        if ! pid_alive "${APP_WORKER_PID}"; then
            die "app-worker exited; see ${APP_WORKER_LOG}"
        fi
        if ! pid_alive "${FRONTEND_PID}"; then
            die "frontend exited; see ${FRONTEND_LOG}"
        fi
        sleep 2
    done
}

case "${1:-start}" in
    start)
        start_stack
        ;;
    dev)
        # 开发模式:next dev + HMR,并启用仅开发生效的 better-auth 配置(见 start_frontend)。
        FRONTEND_MODE=dev
        start_stack
        ;;
    prod)
        # 生产模式:next build + next start。
        FRONTEND_MODE=prod
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    restart)
        stop_stack
        start_stack
        ;;
    status)
        status_stack
        ;;
    logs)
        logs_stack
        ;;
    foreground|serve)
        foreground_stack
        ;;
    *)
        die "usage: $0 [start|dev|prod|stop|restart|status|logs|foreground]"
        ;;
esac
