# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776786845`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `422.16`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776787026.168682, 'stop_ts': 1776787146.828738}`

## Detection Summary
- TP: `64`
- FP: `3`
- FN(proxy): `0`
- Precision: `0.9552`
- Recall: `1.0000`
- F1: `0.9771`

## Lead-Time / Delay
- First detection delay sec: `58.281301975250244`
- Mean detection delay sec: `84.37340331450105`
- Median detection delay sec: `79.09722602367401`

## SOM Runtime Metrics
- Training duration sec: `0.346`
- Bootstrap samples: `350`
- Avg scoring latency ms: `5.838`
- BMU coverage count: `104`
- Scored by phase: `{'chaos': 104, 'cooldown': 159, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `104`
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
- `tier_a_disk_io_bytes_per_sec`: `64`
- `tier_a_cpu_usage_cores`: `33`
- `tier_a_memory_working_set_bytes`: `7`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776786845/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.