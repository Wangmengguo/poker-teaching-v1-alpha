#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[%s] [run_cloud_pipeline] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

# Resolve repository root assuming the script lives in <repo>/scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORKDIR="${1:-${REPO_ROOT}}"
OUTDIR="${WORKDIR}/artifacts"
REPORT_DIR="${WORKDIR}/reports"
REPORT="${REPORT_DIR}/m2_smoke_cloud.md"
PYTHON_BIN="${PYTHON_BIN:-python}"

CREATED_TREE=0
CREATED_TRANSITIONS=0
CREATED_EV_CACHE=0

cleanup_on_exit() {
    local exit_code=$?
    if [ "${exit_code}" -ne 0 ]; then
        log "Pipeline failed (exit=${exit_code}); cleaning up transient artifacts"
        if [ "${CREATED_TREE}" -eq 1 ]; then
            rm -f "${OUTDIR}/tree_flat.json"
        fi
        if [ "${CREATED_TRANSITIONS}" -eq 1 ]; then
            rm -rf "${OUTDIR}/transitions"
        fi
        if [ "${CREATED_EV_CACHE}" -eq 1 ]; then
            rm -f "${OUTDIR}/ev_cache/turn_leaf.npz"
        fi
    else
        log "Pipeline completed successfully"
    fi
}
trap cleanup_on_exit EXIT

log "Starting cloud pipeline with workspace ${WORKDIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    log "Python binary '${PYTHON_BIN}' not found on PATH"
    exit 1
fi
log "Using Python binary: $(command -v "${PYTHON_BIN}")"

REQUIRED_MODULES=(numpy scipy)
if ! "${PYTHON_BIN}" - <<'PY' "${REQUIRED_MODULES[@]}"; then
import importlib.util
import sys
missing = [m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit("missing:" + ",".join(missing))
PY
then
    log "Missing required Python modules: ${REQUIRED_MODULES[*]}"
    exit 1
fi
log "Verified Python modules: ${REQUIRED_MODULES[*]}"

if ! "${PYTHON_BIN}" - <<'PY'
import importlib.util
import sys
module = sys.argv[1]
raise SystemExit(0 if importlib.util.find_spec(module) else 1)
PY
"highspy"; then
    log "Optional module 'highspy' not detected; solver will fall back to scipy.linprog when necessary"
else
    log "Detected optional module 'highspy'"
fi

mkdir -p "${OUTDIR}" "${REPORT_DIR}"

if [ ! -f "${OUTDIR}/tree_flat.json" ]; then
    CREATED_TREE=1
    log "Building tree artifact at ${OUTDIR}/tree_flat.json"
    start_ts=$(date +%s)
    "${PYTHON_BIN}" -m tools.build_tree \
        --config "${REPO_ROOT}/configs/trees/hu_discrete_2cap.yaml" \
        --out "${OUTDIR}/tree_flat.json"
    duration=$(( $(date +%s) - start_ts ))
    log "Tree artifact ready (elapsed ${duration}s)"
else
    log "Reusing existing tree artifact ${OUTDIR}/tree_flat.json"
fi

if [ ! -d "${OUTDIR}/transitions" ]; then
    CREATED_TRANSITIONS=1
    log "Estimating transition artifacts under ${OUTDIR}/transitions"
    mkdir -p "${OUTDIR}/transitions"
    start_ts=$(date +%s)
    "${PYTHON_BIN}" -m tools.estimate_transitions \
        --from flop --to turn --samples 200000 \
        --out "${OUTDIR}/transitions/flop_to_turn.json"
    "${PYTHON_BIN}" -m tools.estimate_transitions \
        --from turn --to river --samples 200000 \
        --out "${OUTDIR}/transitions/turn_to_river.json"
    duration=$(( $(date +%s) - start_ts ))
    log "Transition artifacts ready (elapsed ${duration}s)"
else
    log "Reusing existing transition directory ${OUTDIR}/transitions"
fi

if [ ! -f "${OUTDIR}/ev_cache/turn_leaf.npz" ]; then
    CREATED_EV_CACHE=1
    log "Generating turn leaf EV cache at ${OUTDIR}/ev_cache/turn_leaf.npz"
    mkdir -p "${OUTDIR}/ev_cache"
    start_ts=$(date +%s)
    "${PYTHON_BIN}" -m tools.cache_turn_leaf_ev \
        --trans "${OUTDIR}/transitions/turn_to_river.json" \
        --out "${OUTDIR}/ev_cache/turn_leaf.npz"
    duration=$(( $(date +%s) - start_ts ))
    log "Turn leaf EV cache ready (elapsed ${duration}s)"
else
    log "Reusing existing EV cache ${OUTDIR}/ev_cache/turn_leaf.npz"
fi

log "Solving LP to produce strategy solution"
start_ts=$(date +%s)
"${PYTHON_BIN}" -m tools.solve_lp \
    --tree "${OUTDIR}/tree_flat.json" \
    --buckets "${REPO_ROOT}/configs/buckets" \
    --transitions "${OUTDIR}/transitions" \
    --leaf_ev "${OUTDIR}/ev_cache/turn_leaf.npz" \
    --solver auto \
    --out "${OUTDIR}/lp_solution.json" \
    --log-meta
duration=$(( $(date +%s) - start_ts ))
log "LP solution written to ${OUTDIR}/lp_solution.json (elapsed ${duration}s)"

log "Exporting policies from LP solution"
start_ts=$(date +%s)
"${PYTHON_BIN}" -m tools.export_policy \
    --solution "${OUTDIR}/lp_solution.json" \
    --out "${OUTDIR}/policies" \
    --compress \
    --debug-jsonl "${OUTDIR}/policy_sample.jsonl"
duration=$(( $(date +%s) - start_ts ))
log "Policy export finished (elapsed ${duration}s)"

log "Running M2 smoke test report"
start_ts=$(date +%s)
"${PYTHON_BIN}" -m tools.m2_smoke \
    --workspace "${WORKDIR}" \
    --out "${REPORT}" \
    --reuse
duration=$(( $(date +%s) - start_ts ))
log "Smoke test report available at ${REPORT} (elapsed ${duration}s)"
