# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776569012`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `542.39`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776569375.086638, 'stop_ts': 1776569495.1410592}`

## Detection Summary
- TP: `182`
- FP: `39`
- FN(proxy): `0`
- Precision: `0.8235`
- Recall: `1.0000`
- F1: `0.9032`

## Lead-Time / Delay
- First detection delay sec: `22.07348942756653`
- Mean detection delay sec: `71.31262028479314`
- Median detection delay sec: `71.43675410747528`

## SOM Runtime Metrics
- Training duration sec: `0.318`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.639`
- BMU coverage count: `138`
- Scored by phase: `{'chaos': 320, 'cooldown': 335, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `320`
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
- `tier_a_cpu_usage_cores`: `166`
- `tier_a_disk_read_bytes_per_sec`: `53`
- `tier_a_memory_working_set_bytes`: `45`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776569012/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.