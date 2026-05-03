# Cassandra UBL Run Report

## Run Metadata
- Run ID: `nb-pretrained-1776919789`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `123.6`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': None, 'stop_ts': None}`

## Detection Summary
- TP: `0`
- FP: `69`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.0`
- Bootstrap samples: `0`
- Avg scoring latency ms: `3.57`
- BMU coverage count: `71`
- Scored by phase: `{'chaos': 80, 'cooldown': 105, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `6`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `80`
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
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/nb-pretrained-1776919789/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.