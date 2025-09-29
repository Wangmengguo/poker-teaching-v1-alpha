#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[%s] [run_cloud_pipeline] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

# Resolve repository root assuming the script lives in <repo>/scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORKDIR="${REPO_ROOT}"
if [[ $# -gt 0 && "${1}" != --* ]]; then
    WORKDIR="${1}"
    shift
fi

OUTDIR="${WORKDIR}/artifacts"
REPORT_DIR="${WORKDIR}/reports"
REPORT="${REPORT_DIR}/m2_smoke_cloud.md"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    log "Python binary '${PYTHON_BIN}' not found on PATH"
    exit 1
fi
log "Using Python binary: $(command -v "${PYTHON_BIN}")"

mkdir -p "${OUTDIR}" "${REPORT_DIR}"

declare -a EXTRA_ARGS=("$@")
declare -a DEFAULT_FLAGS=()
reuse_or_force=false
for arg in "${EXTRA_ARGS[@]}"; do
    if [[ "${arg}" == "--reuse" || "${arg}" == "--force" ]]; then
        reuse_or_force=true
        break
    fi
done
if ! ${reuse_or_force}; then
    DEFAULT_FLAGS+=("--reuse")
fi

log "Invoking tools.m2_smoke one-click pipeline in ${WORKDIR}"
"${PYTHON_BIN}" -m tools.m2_smoke \
    --workspace "${WORKDIR}" \
    --out "${REPORT}" \
    "${DEFAULT_FLAGS[@]}" \
    "${EXTRA_ARGS[@]}"

log "Pipeline completed; artifacts under ${OUTDIR} and report at ${REPORT}"
