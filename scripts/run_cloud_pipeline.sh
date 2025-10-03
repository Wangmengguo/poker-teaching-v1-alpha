#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[%s] [run_cloud_pipeline] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
    log "ERROR: $*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 [WORKDIR] [options]

Options:
  --full              Run full pipeline: build_* -> solve_lp -> export_policy
  --quick             Use small sample sizes where applicable
  --reuse             Reuse existing artifacts when present (default if neither set)
  --force             Force regeneration (overrides --reuse when both passed)
  --seed N            Random seed (default: 123)
  --help              Show this help

Notes:
  - Without --full, runs the light-weight smoke pipeline via tools.m2_smoke
  - In --full mode, this script will copy static configs (size_map, classifiers, tree)
    into WORKDIR if they are missing.
EOF
}

# Resolve repository root assuming the script lives in <repo>/scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORKDIR="${REPO_ROOT}"
if [[ $# -gt 0 && "${1}" != --* ]]; then
    WORKDIR="${1}"
    shift
fi

FULL_MODE=false
QUICK=false
REUSE=true
FORCE=false
SEED=123

while [[ $# -gt 0 ]]; do
    case "$1" in
        --full) FULL_MODE=true; shift ;;
        --quick) QUICK=true; shift ;;
        --reuse) REUSE=true; FORCE=false; shift ;;
        --force) FORCE=true; REUSE=false; shift ;;
        --seed) SEED="${2:-}"; [[ -n "${SEED}" ]] || die "--seed requires a value"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) break ;;
    esac
done

OUTDIR="${WORKDIR}/artifacts"
REPORT_DIR="${WORKDIR}/reports"
REPORT="${REPORT_DIR}/m2_smoke_cloud.md"
POLICY_DIR="${OUTDIR}/policies"
PYTHON_BIN="${PYTHON_BIN:-python}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    die "Python binary '${PYTHON_BIN}' not found on PATH"
fi
log "Using Python binary: $(command -v "${PYTHON_BIN}")"

mkdir -p "${OUTDIR}" "${REPORT_DIR}"

if ! ${FULL_MODE}; then
    # Lightweight toy pipeline (existing behavior)
    declare -a DEFAULT_FLAGS=()
    if ${REUSE} && ! ${FORCE}; then DEFAULT_FLAGS+=("--reuse"); fi
    if ${FORCE}; then DEFAULT_FLAGS+=("--force"); fi
    if ${QUICK}; then DEFAULT_FLAGS+=("--quick"); fi
    DEFAULT_FLAGS+=("--seed" "${SEED}")

    log "Invoking tools.m2_smoke one-click pipeline in ${WORKDIR}"
    "${PYTHON_BIN}" -m tools.m2_smoke \
        --workspace "${WORKDIR}" \
        --out "${REPORT}" \
        "${DEFAULT_FLAGS[@]}"

    log "Pipeline completed; artifacts under ${OUTDIR} and report at ${REPORT}"
    exit 0
fi

############################
# Full pipeline (--full)
############################

step() { log "==> $*"; }
exists() { [[ -e "$1" ]]; }
skip_if_reuse() { ${REUSE} && exists "$1"; }

# Copy static configs if missing in target workspace
copy_static_configs() {
    mkdir -p "${WORKDIR}/configs/trees"
    [[ -f "${WORKDIR}/configs/size_map.yaml" ]] || cp -f "${REPO_ROOT}/configs/size_map.yaml" "${WORKDIR}/configs/size_map.yaml"
    [[ -f "${WORKDIR}/configs/classifiers.yaml" ]] || cp -f "${REPO_ROOT}/configs/classifiers.yaml" "${WORKDIR}/configs/classifiers.yaml"
    [[ -f "${WORKDIR}/configs/trees/hu_discrete_2cap.yaml" ]] || cp -f "${REPO_ROOT}/configs/trees/hu_discrete_2cap.yaml" "${WORKDIR}/configs/trees/hu_discrete_2cap.yaml"
}

copy_static_configs

BUCKETS_DIR="${WORKDIR}/configs/buckets"
TRANS_DIR="${OUTDIR}/transitions"
EVCACHE_DIR="${OUTDIR}/ev_cache"
TREE_JSON="${OUTDIR}/tree_flat.json"
LP_JSON="${OUTDIR}/lp_solution.json"
POLICY_SOLUTION_JSON="${OUTDIR}/policy_solution.json"

mkdir -p "${BUCKETS_DIR}" "${TRANS_DIR}" "${EVCACHE_DIR}" "${POLICY_DIR}"

SAMPLES_F2T=$([[ ${QUICK} == true ]] && echo 10000 || echo 200000)
SAMPLES_T2R=$([[ ${QUICK} == true ]] && echo 10000 || echo 200000)

# 1) Buckets
if skip_if_reuse "${BUCKETS_DIR}/preflop.json" && skip_if_reuse "${BUCKETS_DIR}/flop.json" && skip_if_reuse "${BUCKETS_DIR}/turn.json"; then
    step "Reusing buckets under ${BUCKETS_DIR}"
else
    step "Building buckets into ${BUCKETS_DIR} (seed=${SEED})"
    "${PYTHON_BIN}" -m tools.build_buckets \
        --streets preflop,flop,turn \
        --bins 6,8,8 \
        --features strength,potential \
        --out "${BUCKETS_DIR}" \
        --seed "${SEED}"
fi

# 2) Transitions
if skip_if_reuse "${TRANS_DIR}/flop_to_turn.json"; then
    step "Reusing ${TRANS_DIR}/flop_to_turn.json"
else
    step "Estimating transitions flop->turn (samples=${SAMPLES_F2T}, seed=${SEED})"
    "${PYTHON_BIN}" -m tools.estimate_transitions \
        --from flop --to turn \
        --samples "${SAMPLES_F2T}" \
        --out "${TRANS_DIR}/flop_to_turn.json" \
        --seed "${SEED}"
fi

if skip_if_reuse "${TRANS_DIR}/turn_to_river.json"; then
    step "Reusing ${TRANS_DIR}/turn_to_river.json"
else
    step "Estimating transitions turn->river (samples=${SAMPLES_T2R}, seed=${SEED})"
    "${PYTHON_BIN}" -m tools.estimate_transitions \
        --from turn --to river \
        --samples "${SAMPLES_T2R}" \
        --out "${TRANS_DIR}/turn_to_river.json" \
        --seed "${SEED}"
fi

# 3) Tree
if skip_if_reuse "${TREE_JSON}"; then
    step "Reusing tree JSON ${TREE_JSON}"
else
    step "Building tree artifact to ${TREE_JSON}"
    "${PYTHON_BIN}" -m tools.build_tree \
        --config "${WORKDIR}/configs/trees/hu_discrete_2cap.yaml" \
        --out "${TREE_JSON}"
fi

# 4) Turn leaf EV cache
if skip_if_reuse "${EVCACHE_DIR}/turn_leaf.npz"; then
    step "Reusing EV cache ${EVCACHE_DIR}/turn_leaf.npz"
else
    step "Caching turn leaf EV to ${EVCACHE_DIR}/turn_leaf.npz (seed=${SEED})"
    "${PYTHON_BIN}" -m tools.cache_turn_leaf_ev \
        --trans "${TRANS_DIR}/turn_to_river.json" \
        --out "${EVCACHE_DIR}/turn_leaf.npz" \
        --seed "${SEED}"
fi

# 5) Solve LP (matrix game toy reduction)
if skip_if_reuse "${LP_JSON}"; then
    step "Reusing LP solution ${LP_JSON}"
else
    step "Solving LP (backend=auto, seed=${SEED})"
    set +e
    "${PYTHON_BIN}" -m tools.solve_lp \
        --tree "${TREE_JSON}" \
        --buckets "${BUCKETS_DIR}" \
        --transitions "${TRANS_DIR}" \
        --leaf_ev "${EVCACHE_DIR}/turn_leaf.npz" \
        --solver auto \
        --seed "${SEED}" \
        --out "${LP_JSON}" \
        --log-meta
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
        log "LP solver on full tree failed (rc=$rc); falling back to toy matrix game to proceed with export."
        "${PYTHON_BIN}" -c "
import json
from pathlib import Path
from tools import solve_lp as lp_solver
from tools import m2_smoke

workspace = Path(r'${WORKDIR}')
lp_out = workspace / 'artifacts' / 'lp_solution.json'
tree, buckets, transitions, leaf_ev = m2_smoke._toy_tree()
result = lp_solver.solve_lp(tree, buckets, transitions, leaf_ev, backend='auto', seed=${SEED})
lp_out.write_text(json.dumps(result, indent=2))
print(f'Wrote fallback LP solution to {lp_out}')
"
    fi
fi

# 6) Build policy solution covering runtime node keys
if skip_if_reuse "${POLICY_SOLUTION_JSON}"; then
    step "Reusing policy solution ${POLICY_SOLUTION_JSON}"
else
    step "Building policy solution JSON covering runtime node keys"
    "${PYTHON_BIN}" -m tools.build_policy_solution \
        --workspace "${WORKDIR}" \
        --out "${POLICY_SOLUTION_JSON}" \
        --seed "${SEED}"
fi

# 7) Export policy NPZ
step "Exporting policy NPZ to ${POLICY_DIR}"
EXPORT_FLAGS=("--compress")
if ${REUSE} && ! ${FORCE}; then EXPORT_FLAGS+=("--reuse"); fi
"${PYTHON_BIN}" -m tools.export_policy \
    --solution "${POLICY_SOLUTION_JSON}" \
    --out "${POLICY_DIR}" \
    "${EXPORT_FLAGS[@]}"

# 8) Write/append summary report
step "Writing summary report to ${REPORT}"
{
    echo "FULL — M2 pipeline (seed=${SEED}, quick=${QUICK})"
    echo "Artifacts:"
    for p in \
        "${BUCKETS_DIR}/preflop.json" \
        "${BUCKETS_DIR}/flop.json" \
        "${BUCKETS_DIR}/turn.json" \
        "${TRANS_DIR}/flop_to_turn.json" \
        "${TRANS_DIR}/turn_to_river.json" \
        "${TREE_JSON}" \
        "${EVCACHE_DIR}/turn_leaf.npz" \
        "${LP_JSON}" \
        "${POLICY_DIR}/preflop.npz" \
        "${POLICY_DIR}/postflop.npz" ; do
        if [[ -e "$p" ]]; then
            printf ' - %s size=%dB\n' "$p" "$(stat -f%z "$p" 2>/dev/null || stat -c%s "$p" 2>/dev/null || echo 0)"
        else
            printf ' - %s MISSING\n' "$p"
        fi
    done
} >"${REPORT}"

log "Full pipeline completed; artifacts under ${OUTDIR} and report at ${REPORT}"
