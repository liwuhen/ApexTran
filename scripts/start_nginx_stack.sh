#!/usr/bin/env bash
#
# Start ApexTran behind a local Nginx reverse proxy.
#
# Default topology:
#   Nginx :80 -> frontend 127.0.0.1:3000
#             -> backend  127.0.0.1:8000
#
# Commands:
#   scripts/start_nginx_stack.sh start
#   scripts/start_nginx_stack.sh stop
#   scripts/start_nginx_stack.sh restart
#   scripts/start_nginx_stack.sh status
#   scripts/start_nginx_stack.sh logs
#   scripts/start_nginx_stack.sh foreground

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
        env ApexTran_WEB_HOST="${BACKEND_HOST}" ApexTran_WEB_PORT="${BACKEND_PORT}" uv run ApexTran web
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
                    BETTER_AUTH_BASE_URL="${BETTER_AUTH_BASE_URL:-${PUBLIC_BASE_URL}}" \
                    corepack pnpm build
                )
            fi
            start_process_in_dir \
                "frontend" \
                "${FRONTEND_PID}" \
                "${FRONTEND_LOG}" \
                "${FRONTEND_DIR}" \
                env BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET}" \
                    BETTER_AUTH_BASE_URL="${BETTER_AUTH_BASE_URL:-${PUBLIC_BASE_URL}}" \
                    corepack pnpm exec next start --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
            ;;
        dev)
            start_process_in_dir \
                "frontend" \
                "${FRONTEND_PID}" \
                "${FRONTEND_LOG}" \
                "${FRONTEND_DIR}" \
                env BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET}" \
                    BETTER_AUTH_BASE_URL="${BETTER_AUTH_BASE_URL:-${PUBLIC_BASE_URL}}" \
                    corepack pnpm exec next dev --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --webpack
            ;;
        *)
            die "unknown APEXTRAN_FRONTEND_MODE=${FRONTEND_MODE}; expected prod or dev"
            ;;
    esac

    wait_for_url "frontend" "http://${FRONTEND_HOST}:${FRONTEND_PORT}/" "${WAIT_SECONDS}"
}

start_stack() {
    preflight_nginx
    start_backend
    start_frontend
    install_nginx_config
    if [[ "${SKIP_NGINX}" != "1" ]] && command -v curl >/dev/null 2>&1 && command -v nginx >/dev/null 2>&1; then
        wait_for_url "nginx" "http://127.0.0.1/nginx-health" 10
    fi
    ok "stack is ready"
    log "public entry       ${PUBLIC_BASE_URL}"
    log "frontend upstream  http://${FRONTEND_HOST}:${FRONTEND_PORT}"
    log "backend upstream   http://${BACKEND_HOST}:${BACKEND_PORT}"
}

stop_stack() {
    stop_process "frontend" "${FRONTEND_PID}"
    stop_process "backend WebChannel" "${BACKEND_PID}"
}

status_stack() {
    if pid_alive "${BACKEND_PID}"; then
        ok "backend running pid $(cat "${BACKEND_PID}")"
    else
        warn "backend stopped"
    fi
    if pid_alive "${FRONTEND_PID}"; then
        ok "frontend running pid $(cat "${FRONTEND_PID}")"
    else
        warn "frontend stopped"
    fi
}

logs_stack() {
    mkdir -p "${LOG_DIR}"
    touch "${BACKEND_LOG}" "${FRONTEND_LOG}"
    tail -n 80 -f "${BACKEND_LOG}" "${FRONTEND_LOG}"
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
        die "usage: $0 [start|stop|restart|status|logs|foreground]"
        ;;
esac
