# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776649564`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `542.53`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776649926.5463989, 'stop_ts': 1776650046.588979}`

## Detection Summary
- TP: `2`
- FP: `12`
- FN(proxy): `0`
- Precision: `0.1429`
- Recall: `1.0000`
- F1: `0.2500`

## Lead-Time / Delay
- First detection delay sec: `71.6669237613678`
- Mean detection delay sec: `71.92552018165588`
- Median detection delay sec: `71.92552018165588`

## SOM Runtime Metrics
- Training duration sec: `0.444`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.147`
- BMU coverage count: `262`
- Scored by phase: `{'chaos': 335, 'cooldown': 337, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `335`
- Chaos min required: `50`
- Message: `ok`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `True`
- lead_time_present: `True`
- chaos_sample_gate_passed: `True`
- fp_within_limit: `False`

## Top Cause Metrics
- `tier_a_disk_read_bytes_per_sec`: `2`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776649564/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.