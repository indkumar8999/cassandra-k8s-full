# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776645615`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `542.43`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776645977.291724, 'stop_ts': 1776646097.337322}`

## Detection Summary
- TP: `12`
- FP: `7`
- FN(proxy): `0`
- Precision: `0.6316`
- Recall: `1.0000`
- F1: `0.7742`

## Lead-Time / Delay
- First detection delay sec: `114.00720739364624`
- Mean detection delay sec: `116.89683540662129`
- Median detection delay sec: `116.89883303642273`

## SOM Runtime Metrics
- Training duration sec: `0.169`
- Bootstrap samples: `350`
- Avg scoring latency ms: `2.333`
- BMU coverage count: `71`
- Scored by phase: `{'chaos': 245, 'cooldown': 128, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `245`
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
- `tier_a_cpu_usage_cores`: `12`
- `tier_a_disk_read_bytes_per_sec`: `12`
- `tier_a_memory_working_set_bytes`: `12`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776645615/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.