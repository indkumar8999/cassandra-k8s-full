# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776297816`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `511.32`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776298237.178299, 'stop_ts': 1776298297.192082}`

## Detection Summary
- TP: `0`
- FP: `162`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.268`
- Bootstrap samples: `350`
- Avg scoring latency ms: `5.674`
- BMU coverage count: `92`
- Scored by phase: `{'normal': 52, 'load': 292, 'chaos': 99, 'cooldown': 50, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `99`
- Chaos min required: `50`
- Message: `ok`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `False`
- lead_time_present: `False`
- chaos_sample_gate_passed: `True`
- fp_within_limit: `False`

## Top Cause Metrics
- No cause hints were emitted.

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776297816/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.