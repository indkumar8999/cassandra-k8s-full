#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

LATEST_RUN="$(ls -dt ./artifacts/* | head -1)"
if [[ -z "${LATEST_RUN}" ]]; then
  echo "No run artifacts found under ./artifacts"
  exit 1
fi

python3 ./reporting/generate_report.py --run-dir "${LATEST_RUN}"
echo "Latest report refreshed: ${LATEST_RUN}"
