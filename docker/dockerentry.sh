#!/usr/bin/env bash
#
# Container bootstrap for ApexTran.
#
#   1. install any user-supplied extra requirements
#   2. activate the image's prebuilt virtualenv
#   3. sync plugins, then hand control to the selected startup mode
#      (or a user-provided startup script, if present)
#
# Paths can be overridden via the ApexTran_VENV / ApexTran_WORKSPACE env vars.

set -eo pipefail

VENV_DIR="${ApexTran_VENV:-/app/.venv}"
WORKSPACE="${ApexTran_WORKSPACE:-/workspace}"
PYTHON_BIN="${VENV_DIR}/bin/python"
ApexTran_BIN="${VENV_DIR}/bin/ApexTran"

log() { printf '[ApexTran] %s\n' "$*"; }

# 1. Pull in extra dependencies a user dropped into the workspace.
extra_reqs="${WORKSPACE}/ApexTran-reqs.txt"
if [[ -f "${extra_reqs}" ]]; then
    log "installing extra requirements from ${extra_reqs}"
    uv pip install -r "${extra_reqs}" -p "${PYTHON_BIN}"
fi

# 2. Enter the environment baked into the image.
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# 3. Make sure plugins are in sync before serving.
log "syncing plugins"
"${ApexTran_BIN}" install

# 4. Launch: prefer a custom startup script, otherwise run the selected mode.
startup="${WORKSPACE}/startup.sh"
if [[ -f "${startup}" ]]; then
    log "handing off to ${startup}"
    exec bash "${startup}"
fi

start_mode="${ApexTran_START_MODE:-gateway}"
case "${start_mode}" in
    gateway|web|chat)
        log "starting ${start_mode}"
        exec "${ApexTran_BIN}" "${start_mode}"
        ;;
    *)
        log "unknown ApexTran_START_MODE=${start_mode}; expected gateway, web, or chat"
        exit 2
        ;;
esac
