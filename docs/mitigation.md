# Mitigation Setup and Flow

Author: Aum Pandya (apandya4@ncsu.edu)

This document explains how mitigation works in this repository.
It is based on `scripts/cassandra_elastic_replicas.sh`.

The script is a **closed-loop scaler** for Cassandra:

1. wait for a scale-out signal
2. scale StatefulSet up (default `3 -> 4`)
3. wait for SLO to stabilize
4. scale StatefulSet down (default `4 -> 3`)

This is technical implementation documentation.
It does not discuss experiment outcomes.

## Script Purpose

File:

- `scripts/cassandra_elastic_replicas.sh`

Primary behavior:

- scale-out trigger can come from learner alarms or Prometheus "bad" signal
- scale-in requires Prometheus "OK" signal stable for a configured window
- supports one-shot mode and daemon mode (repeat cycles)
- writes structured events to JSONL log

## Safety and Scope Notes

The script header clearly states:

- requires `kubectl`, `curl`, `python3`
- demo-grade behavior
- no nodetool decommission flow before scale-down

Use this as lab mitigation automation, not as production ring shrink logic.

## High-Level State Machine

One mitigation cycle:

1. mark cycle start and watch timestamp
2. wait for scale-out condition
3. scale up Cassandra replicas and wait rollout
4. wait for Prometheus SLO stable-OK window
5. scale down to baseline and wait rollout
6. log completion and optionally repeat

If `ELASTIC_DAEMON=0`, cycle runs once and exits.
If `ELASTIC_DAEMON=1`, cycle repeats until stopped or `MAX_CYCLES` reached.

## Required External Inputs

The script needs:

- learner alarms API (`LEARNER_BASE`, default `http://localhost:8100`)
- Prometheus instant query API (`PROMETHEUS_BASE`, default `http://localhost:9090`)
- Cassandra StatefulSet (`NAMESPACE`, `STATEFULSET_NAME`)

It assumes your port-forwards or network routing already work.

## Core Environment Variables

### Cluster and scaling targets

- `NAMESPACE` (default `cassandra-lab`)
- `STATEFULSET_NAME` (default `cassandra`)
- `BASELINE_REPLICAS` (default `3`)
- `MAX_REPLICAS` (default `4`)
- `ROLL_OUT_TIMEOUT` (default `15m`)

### Signal endpoints

- `LEARNER_BASE` (default `http://localhost:8100`)
- `PROMETHEUS_BASE` (default `http://localhost:9090`)

### Prometheus SLO interpretation

- `PROMQL`
- `SLO_THRESHOLD`
- `SLO_COMPARISON` (`lt|lte|gt|gte`, default `lt`)
- `STABLE_OK_SEC` (default `30`)
- `STABLE_BAD_SEC` (default `45`)

If `PROMQL` or `SLO_THRESHOLD` are missing, script falls back to demo defaults:

- `PROMQL='vector(0)'`
- `SLO_THRESHOLD=1`

### Scale-out trigger mode

- `SCALE_OUT_MODE`:
  - `chaos_alarm` (default)
  - `prom_bad`
  - `both`

### Alarm streak controls

- `CONSECUTIVE_CHAOS_ALARMS` (default `3`)
- `ALARM_SLACK_SEC` (default `5`)
- `MIN_ALARM_GAP_SEC` (default `0`)
- `ALARMS_LIMIT` (default `200`)

### Loop behavior

- `ELASTIC_DAEMON` (`0` or `1`, default `0`)
- `MAX_CYCLES` (default `0`, unlimited when daemon mode is on)
- `WAIT_SCALE_OUT_SEC` (default `3600`)
- `WAIT_SCALE_IN_SEC` (default `3600`)
- `POLL_SEC` (default `5`)

### Event logging

- `RUN_LABEL`
- `EVENT_LOG_PATH` (default `./artifacts/elastic_replica_events_<RUN_LABEL>.jsonl`)
- `PUBLISHER_SCRIPT` (default `scripts/publish_demo_event.sh`)

## Scale-Out Trigger Logic

Scale-out path depends on `SCALE_OUT_MODE`.

### Mode: `chaos_alarm`

The script reads learner alarms:

- endpoint: `${LEARNER_BASE}/alarms?limit=${ALARMS_LIMIT}`
- only alarms after cycle `WATCH_START_TS` (with `ALARM_SLACK_SEC`)
- requires `phase == "chaos"`
- requires a streak of `CONSECUTIVE_CHAOS_ALARMS` in chronological order
- optional minimum timestamp gap via `MIN_ALARM_GAP_SEC`

If streak condition is met, scale-out triggers.

### Mode: `prom_bad`

The script runs Prometheus instant query:

- endpoint: `${PROMETHEUS_BASE}/api/v1/query?query=<url-encoded PROMQL>`

`prom_parse()` classifies query result into:

- `ok`
- `bad`
- `empty`
- `nan`
- `err`

Scale-out triggers only if signal is `bad` for continuous `STABLE_BAD_SEC`.

### Mode: `both`

Either condition can trigger:

- chaos alarm streak
- sustained prom bad

## Scale-In Logic

After scale-up and rollout success:

1. script continuously queries Prometheus
2. script requires `ok` state to remain stable for `STABLE_OK_SEC`
3. any non-`ok` result resets stable window
4. once stable-OK threshold is met, script scales down to `BASELINE_REPLICAS`

This is hysteresis to avoid immediate oscillation.

## Rollout and Verification Operations

Scale operations use:

- `kubectl scale statefulset/<name> --replicas=<n>`
- `kubectl rollout status statefulset/<name> --timeout=<ROLL_OUT_TIMEOUT>`

After each rollout, script prints Cassandra pods:

- `kubectl -n <ns> get pods -l app=cassandra -o wide`

At end of scale-down cycle, script attempts:

- `kubectl exec ... nodetool status`

If unavailable, it logs and continues.

## Event Logging Format

`emit_event()` appends JSON lines to `EVENT_LOG_PATH`.

Each event has:

- `ts_utc`
- `event`
- optional `detail`

Common events:

- `run_started`
- `cycle_started`
- `scale_out_signal`
- `scale_up`
- `rollout_up_complete`
- `slo_stable`
- `scale_down`
- `rollout_down_complete`
- `cycle_complete`
- `run_complete`

This log is useful for timeline reconstruction and debugging.

## Practical Run Examples

## 1) Single mitigation cycle (alarm-triggered scale-out)

```bash
export LEARNER_BASE="http://localhost:8100"
export PROMETHEUS_BASE="http://localhost:9090"
export SCALE_OUT_MODE="chaos_alarm"
export CONSECUTIVE_CHAOS_ALARMS=3
export PROMQL='vector(0)'
export SLO_THRESHOLD=1
export SLO_COMPARISON=lt
export STABLE_OK_SEC=30
bash ./scripts/cassandra_elastic_replicas.sh
```

## 2) Scale-out from sustained Prometheus bad signal

```bash
export SCALE_OUT_MODE="prom_bad"
export STABLE_BAD_SEC=45
export PROMQL='<your-promql-expression>'
export SLO_THRESHOLD='<your-threshold>'
export SLO_COMPARISON='lt'
bash ./scripts/cassandra_elastic_replicas.sh
```

## 3) Daemon mode (repeat cycles)

```bash
export ELASTIC_DAEMON=1
export MAX_CYCLES=3
export SCALE_OUT_MODE="both"
bash ./scripts/cassandra_elastic_replicas.sh
```

## 4) Fast lab test (legacy single-alarm trigger)

```bash
export CONSECUTIVE_CHAOS_ALARMS=1
export STABLE_OK_SEC=15
export SCALE_OUT_MODE="chaos_alarm"
bash ./scripts/cassandra_elastic_replicas.sh
```

## Pre-Run Checklist

Before running mitigation:

1. Cassandra StatefulSet is healthy at baseline replicas
2. learner endpoint is reachable (`/alarms`)
3. Prometheus query endpoint is reachable
4. your `PROMQL`, threshold, and comparison direction are correct
5. port-forwards are active if using localhost endpoints
6. you understand this script scales replicas directly

## Common Failure Modes

### Timeout waiting for scale-out signal

Possible reasons:

- no chaos-phase alarm streak
- Prometheus never enters sustained bad state
- incorrect endpoint URLs

Actions:

- reduce `CONSECUTIVE_CHAOS_ALARMS`
- verify `/alarms` output and `phase` values
- verify `PROMQL` and `SLO_THRESHOLD`

### Timeout waiting for scale-in

Possible reasons:

- SLO signal never stable in OK band
- comparison direction (`lt/lte/gt/gte`) is wrong
- threshold too strict

Actions:

- inspect query response values
- tune threshold/comparison
- increase `WAIT_SCALE_IN_SEC`

### Thrashing concerns

Current protections:

- stable-bad window for scale-out (`prom_bad`)
- stable-ok window for scale-in
- per-cycle fresh watch timestamp prevents stale alarm reuse

## Related Files

- `scripts/cassandra_elastic_replicas.sh`
- `scripts/publish_demo_event.sh`
- `orchestrator/run_scenario.py`
- `docs/operations-and-troubleshooting.md`
