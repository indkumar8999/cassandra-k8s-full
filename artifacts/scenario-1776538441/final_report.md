# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776538441`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `457.52`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776538628.341388, 'stop_ts': 1776538808.408088}`

## Detection Summary
- TP: `241`
- FP: `1`
- FN(proxy): `0`
- Precision: `0.9959`
- Recall: `1.0000`
- F1: `0.9979`

## Lead-Time / Delay
- First detection delay sec: `1.6098134517669678`
- Mean detection delay sec: `113.83304947639402`
- Median detection delay sec: `114.14071273803711`

## SOM Runtime Metrics
- Training duration sec: `0.335`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.694`
- BMU coverage count: `92`
- Scored by phase: `{'chaos': 328, 'cooldown': 163, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `328`
- Chaos min required: `50`
- Message: `ok`

## Acceptance Criteria
- Passed: `True`
- Max FP allowed: `10`
- tp_during_chaos: `True`
- lead_time_present: `True`
- chaos_sample_gate_passed: `True`
- fp_within_limit: `True`

## Top Cause Metrics
- `tier_a_disk_read_bytes_per_sec`: `241`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776538441/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.