#!/usr/bin/env bash
set -euo pipefail

EVENT_NAME="${1:-}"
DETAIL="${2:-}"
EVENT_SOURCE="${3:-auto-scale-script}"
RUN_LABEL="${4:-manual}"

DEMO_EVENT_ENDPOINT="${DEMO_EVENT_ENDPOINT:-http://localhost:8100/demo-event}"

if [[ -z "${EVENT_NAME}" ]]; then
  echo "[demo-event][ERROR] missing event name" >&2
  exit 2
fi

PAYLOAD="$(
  python3 - "${EVENT_NAME}" "${DETAIL}" "${EVENT_SOURCE}" "${RUN_LABEL}" <<'PY'
import json
import sys
import time

event_name = sys.argv[1]
detail = sys.argv[2]
source = sys.argv[3]
run_label = sys.argv[4]

payload = {
    "event": event_name,
    "detail": detail,
    "source": source,
    "run_label": run_label,
    "ts": time.time(),
}
print(json.dumps(payload, separators=(",", ":")))
PY
)"

HTTP_CODE="$(
  curl -sS -o /tmp/demo_event_publish.out -w "%{http_code}" \
    -X POST "${DEMO_EVENT_ENDPOINT}" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" || true
)"

if [[ "${HTTP_CODE}" =~ ^2[0-9][0-9]$ ]]; then
  echo "[demo-event] published event=${EVENT_NAME} source=${EVENT_SOURCE} run=${RUN_LABEL}"
  exit 0
fi

echo "[demo-event][WARN] publish failed (http=${HTTP_CODE:-unknown}) endpoint=${DEMO_EVENT_ENDPOINT}" >&2
if [[ -f /tmp/demo_event_publish.out ]]; then
  cat /tmp/demo_event_publish.out >&2
fi
exit 0
