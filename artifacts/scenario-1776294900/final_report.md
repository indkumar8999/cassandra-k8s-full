# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776294900`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `491.22`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776295121.815061, 'stop_ts': 1776295301.830959}`

## Detection Summary
- TP: `164`
- FP: `103`
- FN(proxy): `0`
- Precision: `0.6142`
- Recall: `1.0000`
- F1: `0.7610`

## Lead-Time / Delay
- First detection delay sec: `2.834092855453491`
- Mean detection delay sec: `95.60932295642247`
- Median detection delay sec: `100.65424311161041`

## SOM Runtime Metrics
- Training duration sec: `0.101`
- Bootstrap samples: `120`
- Avg scoring latency ms: `3.689`
- BMU coverage count: `146`
- Scored by phase: `{'normal': 150, 'load': 98, 'chaos': 290, 'cooldown': 146, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `290`
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
- `tier_a_disk_write_bytes_per_sec__cassandra-0`: `164`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776294900/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.