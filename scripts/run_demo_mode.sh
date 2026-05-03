#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 ./orchestrator/run_scenario.py \
  --normal-sec 45 \
  --load-sec 45 \
  --chaos-sec 90 \
  --cooldown-sec 45 \
  --fault-profile "${1:-network-congestion-like}" \
  --load-profile "${2:-high}" \
  --output-dir ./artifacts

LATEST_RUN="$(ls -dt ./artifacts/* | head -1)"
python3 ./reporting/generate_report.py --run-dir "${LATEST_RUN}"
echo "Demo artifacts generated in ${LATEST_RUN}"
