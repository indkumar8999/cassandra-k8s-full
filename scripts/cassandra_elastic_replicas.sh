#!/usr/bin/env bash
#
# Wait for scale-out signal -> Cassandra StatefulSet -> MAX_REPLICAS (default 4),
# then wait for SLO OK (Prometheus) -> scale back to BASELINE_REPLICAS (default 3).
#
# Scale-out when SCALE_OUT_MODE includes chaos_alarm (default):
#   Requires CONSECUTIVE_CHAOS_ALARMS (default 3) chaos-phase alarms in a row in
#   chronological /alarms order after WATCH_START_TS (slack ALARM_SLACK_SEC), with
#   optional MIN_ALARM_GAP_SEC between successive chaos alarm timestamps.
#   Set CONSECUTIVE_CHAOS_ALARMS=1 to restore the old "any single new chaos alarm" behavior.
#
# ELASTIC_DAEMON=1: repeat cycles forever (refresh WATCH_START_TS each cycle). ELASTIC_DAEMON=0 (default):
#   run one cycle and exit. MAX_CYCLES>0 caps iterations when daemon is on.
#
# Stale alarms: each cycle sets a fresh WATCH_START_TS so the same deque entries are not reused.
# /alarms limit=80 — if you need longer history, raise limit in chaos_consecutive_chaos_met curl.
#
# Scale-out (pick SCALE_OUT_MODE):
#   chaos_alarm (default): consecutive chaos-phase alarms (see above), or prom_bad / both.
#   prom_bad:              PromQL instant value NOT in OK band for STABLE_BAD_SEC.
#   both:                  either chaos_alarm streak OR prom_bad triggers scale-out.
#
# Scale-in: Prometheus instant query stays OK for STABLE_OK_SEC (hysteresis), then scale down.
#
# Requires: kubectl, curl, python3. Demo-grade only (no nodetool decommission).
#
# Environment (common):
#   NAMESPACE, STATEFULSET_NAME, BASELINE_REPLICAS (default 3), MAX_REPLICAS (default 4)
#   LEARNER_BASE (default http://localhost:8100)
#   PROMETHEUS_BASE (default http://localhost:9090)
#   PROMQL, SLO_THRESHOLD, SLO_COMPARISON (lt|lte|gt|gte, default lt), STABLE_OK_SEC (default 120)
#   POLL_SEC, ROLL_OUT_TIMEOUT
#   SCALE_OUT_MODE        chaos_alarm | prom_bad | both (default chaos_alarm)
#   STABLE_BAD_SEC        seconds metric must stay "bad" before scale-out when using prom_bad/both (default 45)
#   ALARM_SLACK_SEC       float seconds subtracted from watch start when matching alarm ts (default 5)
#   CONSECUTIVE_CHAOS_ALARMS  chaos streak length for scale-out (default 3; use 1 for legacy)
#   MIN_ALARM_GAP_SEC     min seconds between successive chaos alarm ts in the streak tail (default 0)
#   ELASTIC_DAEMON        1 = loop cycles forever; 0 = single cycle (default)
#   MAX_CYCLES            when ELASTIC_DAEMON=1, stop after this many cycles (0 = unlimited)
#   WAIT_SCALE_OUT_SEC    timeout waiting to scale out per cycle (default 3600)
#   WAIT_SCALE_IN_SEC     timeout waiting to scale in per cycle (default 3600)
#   RUN_LABEL, EVENT_LOG_PATH, PUBLISHER_SCRIPT
#
# If PROMQL or SLO_THRESHOLD unset for scale-in, a trivial demo query is used with a stderr warning.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

NAMESPACE="${NAMESPACE:-cassandra-lab}"
STATEFULSET_NAME="${STATEFULSET_NAME:-cassandra}"
BASELINE_REPLICAS="${BASELINE_REPLICAS:-3}"
MAX_REPLICAS="${MAX_REPLICAS:-4}"
LEARNER_BASE="${LEARNER_BASE:-http://localhost:8100}"
PROMETHEUS_BASE="${PROMETHEUS_BASE:-http://localhost:9090}"
PROMQL="${PROMQL:-}"
SLO_THRESHOLD="${SLO_THRESHOLD:-}"
SLO_COMPARISON="${SLO_COMPARISON:-lt}"
STABLE_OK_SEC="${STABLE_OK_SEC:-30}"
STABLE_BAD_SEC="${STABLE_BAD_SEC:-45}"
POLL_SEC="${POLL_SEC:-5}"
ROLL_OUT_TIMEOUT="${ROLL_OUT_TIMEOUT:-15m}"
SCALE_OUT_MODE="${SCALE_OUT_MODE:-chaos_alarm}"
ALARM_SLACK_SEC="${ALARM_SLACK_SEC:-5}"
WAIT_SCALE_OUT_SEC="${WAIT_SCALE_OUT_SEC:-3600}"
WAIT_SCALE_IN_SEC="${WAIT_SCALE_IN_SEC:-3600}"
RUN_LABEL="${RUN_LABEL:-$(date -u +%Y%m%dT%H%M%SZ)}"
EVENT_LOG_PATH="${EVENT_LOG_PATH:-./artifacts/elastic_replica_events_${RUN_LABEL}.jsonl}"
PUBLISHER_SCRIPT="${PUBLISHER_SCRIPT:-${SCRIPT_DIR}/publish_demo_event.sh}"
ELASTIC_DAEMON="${ELASTIC_DAEMON:-0}"
CONSECUTIVE_CHAOS_ALARMS="${CONSECUTIVE_CHAOS_ALARMS:-3}"
MIN_ALARM_GAP_SEC="${MIN_ALARM_GAP_SEC:-0}"
MAX_CYCLES="${MAX_CYCLES:-0}"
ALARMS_LIMIT="${ALARMS_LIMIT:-200}"
mkdir -p "$(dirname "${EVENT_LOG_PATH}")"

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log() { echo "[elastic][$(now_iso)] $*"; }

die() { echo "[elastic][ERROR] $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

emit_event() {
  local event="$1"
  local detail="${2:-}"
  python3 - "$event" "$(now_iso)" "$detail" >> "${EVENT_LOG_PATH}" <<'PY'
import json, sys
event, ts, detail = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {"ts_utc": ts, "event": event}
if detail:
    payload["detail"] = detail
print(json.dumps(payload, separators=(",", ":")))
PY
  if [[ -x "${PUBLISHER_SCRIPT}" ]]; then
    "${PUBLISHER_SCRIPT}" "${event}" "${detail}" "elastic-replicas" "${RUN_LABEL}" || true
  fi
}

require_cmd kubectl
require_cmd curl
require_cmd python3

case "${SCALE_OUT_MODE}" in
  chaos_alarm | prom_bad | both) ;;
  *) die "SCALE_OUT_MODE must be chaos_alarm, prom_bad, or both (got ${SCALE_OUT_MODE})" ;;
esac

case "${SLO_COMPARISON}" in
  lt | lte | gt | gte) ;;
  *) die "SLO_COMPARISON must be lt lte gt gte" ;;
esac

case "${ELASTIC_DAEMON}" in
  0 | 1) ;;
  *) die "ELASTIC_DAEMON must be 0 or 1 (got ${ELASTIC_DAEMON})" ;;
esac

[[ "${CONSECUTIVE_CHAOS_ALARMS}" =~ ^[0-9]+$ ]] || die "CONSECUTIVE_CHAOS_ALARMS must be a non-negative integer"
[[ "${CONSECUTIVE_CHAOS_ALARMS}" -ge 1 ]] || die "CONSECUTIVE_CHAOS_ALARMS must be >= 1"

[[ "${MAX_CYCLES}" =~ ^[0-9]+$ ]] || die "MAX_CYCLES must be a non-negative integer"

# --- optional demo defaults for scale-in only ---
if [[ -z "${PROMQL// }" || -z "${SLO_THRESHOLD// }" ]]; then
  echo "[elastic] WARNING: PROMQL and/or SLO_THRESHOLD unset — using trivial demo vector(0)<1 for scale-in." >&2
  PROMQL='vector(0)'
  SLO_THRESHOLD=1
  STABLE_OK_SEC="${STABLE_OK_SEC:-15}"
fi
export PROMQL SLO_THRESHOLD SLO_COMPARISON

STABLE_OK_INT="${STABLE_OK_SEC%.*}"
STABLE_OK_INT="${STABLE_OK_INT:-0}"
[[ "${STABLE_OK_INT}" -ge 1 ]] || die "STABLE_OK_SEC must be >= 1 (integer part)"

STABLE_BAD_INT="${STABLE_BAD_SEC%.*}"
STABLE_BAD_INT="${STABLE_BAD_INT:-0}"
[[ "${STABLE_BAD_INT}" -ge 1 ]] || die "STABLE_BAD_SEC must be >= 1 (integer part)"

ENC_QUERY="$(python3 -c 'import urllib.parse, os; print(urllib.parse.quote(os.environ["PROMQL"], safe=""))')"
QUERY_URL="${PROMETHEUS_BASE%/}/api/v1/query?query=${ENC_QUERY}"

log "event log: ${EVENT_LOG_PATH}"
log "scale_out_mode=${SCALE_OUT_MODE} daemon=${ELASTIC_DAEMON} max_cycles=${MAX_CYCLES} consecutive_chaos=${CONSECUTIVE_CHAOS_ALARMS} learner=${LEARNER_BASE} prom=${PROMETHEUS_BASE}"
emit_event "run_started" "mode=${SCALE_OUT_MODE} daemon=${ELASTIC_DAEMON} max=${MAX_REPLICAS} baseline=${BASELINE_REPLICAS} consecutive_chaos=${CONSECUTIVE_CHAOS_ALARMS}"

# --- Prometheus parse: returns ok|bad|empty|nan|err|... same as scale-in script ---
prom_parse() {
  local body="$1"
  printf '%s' "${body}" | python3 -c '
import json, os, sys
comp = os.environ.get("SLO_COMPARISON", "lt")
thresh_s = os.environ.get("SLO_THRESHOLD", "")
raw = sys.stdin.read() or "{}"

def ok_for(value: float, t: float) -> bool:
    if comp == "lt": return value < t
    if comp == "lte": return value <= t
    if comp == "gt": return value > t
    if comp == "gte": return value >= t
    raise SystemExit("bad comp")

try:
    thresh = float(thresh_s)
except ValueError:
    print("err|bad_threshold"); raise SystemExit(0)
try:
    obj = json.loads(raw)
except json.JSONDecodeError:
    print("err|bad_json"); raise SystemExit(0)
if obj.get("status") != "success":
    print("err|prom_status"); raise SystemExit(0)
results = (obj.get("data") or {}).get("result") or []
if not results:
    print("empty|"); raise SystemExit(0)
val_s = (results[0].get("value") or [None, ""])[1]
if val_s is None or val_s == "":
    print("empty|"); raise SystemExit(0)
try:
    val = float(val_s)
except ValueError:
    print("nan|" if str(val_s).lower() == "nan" else "err|bad_value"); raise SystemExit(0)
if val != val:
    print("nan|"); raise SystemExit(0)
state = "ok" if ok_for(val, thresh) else "bad"
print(f"{state}|{val}")
'
}

# --- scale-out: chaos_alarm = N consecutive chaos-phase alarms (chronological streak after WATCH_START_TS) ---
chaos_consecutive_chaos_met() {
  local payload
  payload="$(curl -sS --max-time 10 "${LEARNER_BASE}/alarms?limit=${ALARMS_LIMIT}" 2>/dev/null)" || return 1
  printf '%s' "${payload}" | python3 -c '
import json, os, sys
start = float(os.environ["WATCH_START_TS"])
slack = float(os.environ.get("ALARM_SLACK_SEC", "5"))
need = int(os.environ.get("CONSECUTIVE_CHAOS_ALARMS", "3"))
min_gap = float(os.environ.get("MIN_ALARM_GAP_SEC", "0"))
raw = sys.stdin.read() or "{}"
try:
    obj = json.loads(raw)
except json.JSONDecodeError:
    sys.exit(1)
items = [a for a in (obj.get("items") or []) if isinstance(a, dict)]
rows = []
for a in items:
    try:
        t = float(a.get("ts", 0))
    except (TypeError, ValueError):
        continue
    if t < start - slack:
        continue
    ph = a.get("phase")
    rows.append((t, ph))
rows.sort(key=lambda x: x[0])
streak = 0
last_chaos_ts = None
for t, ph in rows:
    if ph == "chaos":
        if last_chaos_ts is not None and min_gap > 0 and (t - last_chaos_ts) < min_gap - 1e-9:
            streak = 1
        else:
            streak += 1
        last_chaos_ts = t
        if streak >= need:
            print("yes", t)
            sys.exit(0)
    else:
        streak = 0
        last_chaos_ts = None
sys.exit(1)
'
}

# --- one full cycle: scale-out wait -> up -> scale-in wait -> down ---
run_one_elastic_cycle() {
  local cycle_num="$1"

  WATCH_START_TS="$(python3 -c 'import time; print(time.time())')"
  export WATCH_START_TS ALARM_SLACK_SEC CONSECUTIVE_CHAOS_ALARMS MIN_ALARM_GAP_SEC

  log "cycle ${cycle_num} watch_start_ts=${WATCH_START_TS}"
  emit_event "cycle_started" "cycle=${cycle_num} mode=${SCALE_OUT_MODE} watch_start_ts=${WATCH_START_TS}"

  # --- scale-out phase ---
  local CURRENT
  CURRENT="$(kubectl -n "${NAMESPACE}" get statefulset "${STATEFULSET_NAME}" -o jsonpath='{.spec.replicas}' | tr -d ' ')"
  [[ -n "${CURRENT}" ]] || die "cannot read statefulset replicas"

  if [[ "${CURRENT}" -ge "${MAX_REPLICAS}" ]]; then
    log "already at max replicas=${CURRENT}; skipping scale-out wait"
    emit_event "scale_out_skipped" "replicas=${CURRENT} cycle=${cycle_num}"
  else
    log "waiting for scale-out (current=${CURRENT} -> ${MAX_REPLICAS}) consecutive_chaos=${CONSECUTIVE_CHAOS_ALARMS}"
    local START_SO NOW fired BAD_SINCE BAD_FOR KIND VAL BODY PARSED STABLE_FOR
    START_SO="$(date +%s)"
    BAD_SINCE=""
    while true; do
      NOW="$(date +%s)"
      if [[ "$((NOW - START_SO))" -ge "${WAIT_SCALE_OUT_SEC}" ]]; then
        die "timeout waiting for scale-out signal (${WAIT_SCALE_OUT_SEC}s)"
      fi
      fired=0

      if [[ "${SCALE_OUT_MODE}" == "chaos_alarm" || "${SCALE_OUT_MODE}" == "both" ]]; then
        if chaos_consecutive_chaos_met; then
          log "scale-out signal: ${CONSECUTIVE_CHAOS_ALARMS} consecutive chaos-phase alarm(s)"
          emit_event "scale_out_signal" "reason=chaos_alarm consecutive=${CONSECUTIVE_CHAOS_ALARMS} cycle=${cycle_num}"
          fired=1
        fi
      fi

      if [[ "${SCALE_OUT_MODE}" == "prom_bad" || "${SCALE_OUT_MODE}" == "both" ]]; then
        BODY="$(curl -sS --max-time 10 "${QUERY_URL}" 2>/dev/null)" || BODY=""
        PARSED="$(prom_parse "${BODY}")" || PARSED="err|parse"
        KIND="${PARSED%%|*}"
        VAL="${PARSED#*|}"
        if [[ "${KIND}" == "bad" ]]; then
          if [[ -z "${BAD_SINCE}" ]]; then
            BAD_SINCE="${NOW}"
            log "prom SLO bad: value=${VAL} (started bad window)"
          else
            BAD_FOR="$((NOW - BAD_SINCE))"
            log "prom SLO bad: value=${VAL} stable_bad_sec=${BAD_FOR}/${STABLE_BAD_INT}"
            if [[ "${BAD_FOR}" -ge "${STABLE_BAD_INT}" ]]; then
              log "scale-out signal: prom sustained bad"
              emit_event "scale_out_signal" "reason=prom_bad value=${VAL} cycle=${cycle_num}"
              fired=1
            fi
          fi
        else
          BAD_SINCE=""
        fi
      fi

      if [[ "${fired}" -eq 1 ]]; then
        break
      fi
      sleep "${POLL_SEC}"
    done

    log "scaling up: ${CURRENT} -> ${MAX_REPLICAS}"
    emit_event "scale_up" "to=${MAX_REPLICAS} cycle=${cycle_num}"
    kubectl -n "${NAMESPACE}" scale "statefulset/${STATEFULSET_NAME}" --replicas="${MAX_REPLICAS}"
    kubectl -n "${NAMESPACE}" rollout status "statefulset/${STATEFULSET_NAME}" --timeout="${ROLL_OUT_TIMEOUT}"
    emit_event "rollout_up_complete" "replicas=${MAX_REPLICAS} cycle=${cycle_num}"
  fi

  kubectl -n "${NAMESPACE}" get pods -l app=cassandra -o wide || true

  # --- scale-in phase ---
  CURRENT="$(kubectl -n "${NAMESPACE}" get statefulset "${STATEFULSET_NAME}" -o jsonpath='{.spec.replicas}' | tr -d ' ')"
  if [[ "${CURRENT}" -le "${BASELINE_REPLICAS}" ]]; then
    log "already at baseline replicas=${CURRENT}; nothing to scale in (cycle ${cycle_num})"
    emit_event "scale_in_skipped" "replicas=${CURRENT} cycle=${cycle_num}"
    emit_event "cycle_complete" "success=true cycle=${cycle_num} scale_in_skipped=1"
    log "cycle ${cycle_num} done (already baseline)"
    return 0
  fi

  log "waiting for SLO OK to scale in (${CURRENT} -> ${BASELINE_REPLICAS})"
  local START_SI OK_SINCE METRIC_VAL
  START_SI="$(date +%s)"
  OK_SINCE=""
  while true; do
    NOW="$(date +%s)"
    if [[ "$((NOW - START_SI))" -ge "${WAIT_SCALE_IN_SEC}" ]]; then
      die "timeout waiting for SLO-stable scale-in (${WAIT_SCALE_IN_SEC}s)"
    fi
    BODY="$(curl -sS --max-time 10 "${QUERY_URL}" 2>/dev/null)" || BODY=""
    PARSED="$(prom_parse "${BODY}")" || PARSED="err|parse"
    KIND="${PARSED%%|*}"
    METRIC_VAL="${PARSED#*|}"

    case "${KIND}" in
      ok)
        if [[ -z "${OK_SINCE}" ]]; then
          OK_SINCE="${NOW}"
          log "SLO OK value=${METRIC_VAL} (stable window started)"
        else
          STABLE_FOR="$((NOW - OK_SINCE))"
          log "SLO OK value=${METRIC_VAL} stable_ok_sec=${STABLE_FOR}/${STABLE_OK_INT}"
          if [[ "${STABLE_FOR}" -ge "${STABLE_OK_INT}" ]]; then
            emit_event "slo_stable" "value=${METRIC_VAL} cycle=${cycle_num}"
            break
          fi
        fi
        ;;
      *)
        [[ -n "${OK_SINCE}" ]] && log "SLO not OK (${KIND} ${METRIC_VAL}); resetting stable window"
        OK_SINCE=""
        ;;
    esac
    sleep "${POLL_SEC}"
  done

  log "scaling down to baseline ${BASELINE_REPLICAS}"
  emit_event "scale_down" "to=${BASELINE_REPLICAS} cycle=${cycle_num}"
  kubectl -n "${NAMESPACE}" scale "statefulset/${STATEFULSET_NAME}" --replicas="${BASELINE_REPLICAS}"
  kubectl -n "${NAMESPACE}" rollout status "statefulset/${STATEFULSET_NAME}" --timeout="${ROLL_OUT_TIMEOUT}"
  emit_event "rollout_down_complete" "replicas=${BASELINE_REPLICAS} cycle=${cycle_num}"

  kubectl -n "${NAMESPACE}" get pods -l app=cassandra -o wide || true
  kubectl exec -n "${NAMESPACE}" cassandra-0 -- env -u JVM_OPTS nodetool status 2>/dev/null || log "nodetool status skipped/failed"

  emit_event "cycle_complete" "success=true cycle=${cycle_num}"
  log "cycle ${cycle_num} complete"
}

ELASTIC_CYCLE=0
while true; do
  ELASTIC_CYCLE=$((ELASTIC_CYCLE + 1))
  if [[ "${MAX_CYCLES}" -gt 0 && "${ELASTIC_CYCLE}" -gt "${MAX_CYCLES}" ]]; then
    log "MAX_CYCLES=${MAX_CYCLES} reached; exiting"
    emit_event "daemon_stopped" "reason=max_cycles cycles=${MAX_CYCLES}"
    break
  fi

  run_one_elastic_cycle "${ELASTIC_CYCLE}"

  if [[ "${ELASTIC_DAEMON}" != "1" ]]; then
    break
  fi
done

log "done (cycles=${ELASTIC_CYCLE} daemon=${ELASTIC_DAEMON})"
emit_event "run_complete" "cycles=${ELASTIC_CYCLE} daemon=${ELASTIC_DAEMON}"
