#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

NAMESPACE="${NAMESPACE:-cassandra-lab}"
FAULT_PROFILE="${FAULT_PROFILE:-bottleneck-like}"
BOTTLENECK_REPLICAS="${BOTTLENECK_REPLICAS:-1}"
CPU_WORKERS="${CPU_WORKERS:-4}"
MEM_MB="${MEM_MB:-1200}"
LOAD_PROFILE="${LOAD_PROFILE:-high}"

NORMAL_SEC="${NORMAL_SEC:-45}"
LOAD_SEC="${LOAD_SEC:-45}"
CHAOS_SEC="${CHAOS_SEC:-300}"
COOLDOWN_SEC="${COOLDOWN_SEC:-30}"
CHAOS_MIN_SCORED="${CHAOS_MIN_SCORED:-50}"
MAX_FP_ALLOWED="${MAX_FP_ALLOWED:-10}"
BOOTSTRAP_TIMEOUT_SEC="${BOOTSTRAP_TIMEOUT_SEC:-1800}"

require_health() {
  local name="$1"
  local url="$2"
  if ! curl -fsS "${url}" >/dev/null; then
    echo "[batch][ERROR] ${name} endpoint not reachable at ${url}"
    echo "[batch][HINT] start port-forwards for simulator(8080), learner(8100), chaos(8200)"
    exit 1
  fi
}

run_config() {
  local label="$1"
  local smooth_k="$2"
  local streak="$3"
  local threshold="$4"

  echo "[batch] ===== ${label} ====="
  echo "[batch] set learner env: SMOOTH_K=${smooth_k} ANOMALY_STREAK=${streak} THRESHOLD_PERCENTILE=${threshold}"
  kubectl -n "${NAMESPACE}" set env deployment/ubl-learner \
    SMOOTH_K="${smooth_k}" \
    ANOMALY_STREAK="${streak}" \
    THRESHOLD_PERCENTILE="${threshold}" \
    THRESHOLD_RECALC_ENABLED="1" \
    THRESHOLD_RECALC_EVERY_UPDATES="20" >/dev/null
  kubectl -n "${NAMESPACE}" rollout restart deployment/ubl-learner >/dev/null
  kubectl -n "${NAMESPACE}" rollout status deployment/ubl-learner --timeout=300s

  local run_id="scenario-${label}-$(date +%s)"
  echo "[batch] run_id=${run_id}"
  python3 ./orchestrator/run_scenario.py \
    --run-id "${run_id}" \
    --bootstrap-timeout-sec "${BOOTSTRAP_TIMEOUT_SEC}" \
    --normal-sec "${NORMAL_SEC}" \
    --load-sec "${LOAD_SEC}" \
    --chaos-sec "${CHAOS_SEC}" \
    --cooldown-sec "${COOLDOWN_SEC}" \
    --fault-profile "${FAULT_PROFILE}" \
    --cpu-workers "${CPU_WORKERS}" \
    --mem-mb "${MEM_MB}" \
    --bottleneck-replicas "${BOTTLENECK_REPLICAS}" \
    --load-profile "${LOAD_PROFILE}" \
    --output-dir ./artifacts

  python3 ./reporting/generate_report.py \
    --run-dir "./artifacts/${run_id}" \
    --chaos-min-scored "${CHAOS_MIN_SCORED}" \
    --max-fp "${MAX_FP_ALLOWED}" \
    --fail-on-quality-gate
  echo "[batch] completed ${run_id}"
}

echo "[batch] running strict preflight"
make demo-preflight

echo "[batch] validating local service endpoints"
require_health "simulator" "http://localhost:8080/health"
require_health "learner" "http://localhost:8100/health"
require_health "chaos" "http://localhost:8200/health"

# A: balanced baseline
run_config "ubl-a" 3 2 82
# B: recall-oriented
run_config "ubl-b" 1 2 76
# C: aggressive recall
run_config "ubl-c" 1 1 70

echo "[batch] generating grouped ablation report"
python3 ./reporting/generate_report.py \
  --runs-root ./artifacts \
  --chaos-min-scored "${CHAOS_MIN_SCORED}" \
  --max-fp "${MAX_FP_ALLOWED}"
echo "[batch] done"
