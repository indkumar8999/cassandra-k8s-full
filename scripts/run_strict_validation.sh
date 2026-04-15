#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

FAULT_PROFILE="${1:-bottleneck-like}"
LOAD_PROFILE="${2:-high}"
CHAOS_MIN_SCORED="${CHAOS_MIN_SCORED:-50}"
MAX_FP_ALLOWED="${MAX_FP_ALLOWED:-10}"

echo "[validation] running strict preflight"
make demo-preflight

echo "[validation] launching scenario fault=${FAULT_PROFILE} load=${LOAD_PROFILE}"
python3 ./orchestrator/run_scenario.py \
  --normal-sec 60 \
  --load-sec 60 \
  --chaos-sec 240 \
  --cooldown-sec 90 \
  --fault-profile "${FAULT_PROFILE}" \
  --load-profile "${LOAD_PROFILE}" \
  --output-dir ./artifacts

LATEST_RUN="$(ls -dt ./artifacts/* | head -1)"
python3 ./reporting/generate_report.py \
  --run-dir "${LATEST_RUN}" \
  --chaos-min-scored "${CHAOS_MIN_SCORED}" \
  --max-fp "${MAX_FP_ALLOWED}" \
  --fail-on-quality-gate
python3 ./reporting/generate_report.py \
  --runs-root ./artifacts \
  --chaos-min-scored "${CHAOS_MIN_SCORED}" \
  --max-fp "${MAX_FP_ALLOWED}"

echo "[validation] completed: ${LATEST_RUN}"
