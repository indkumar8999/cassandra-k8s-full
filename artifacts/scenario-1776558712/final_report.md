# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776558712`
- Fault profile: `anomaly-university-memory-pressure`
- Load profile: `high`
- Duration sec: `367.46`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776558899.735286, 'stop_ts': 1776559019.751903}`

## Detection Summary
- TP: `41`
- FP: `0`
- FN(proxy): `0`
- Precision: `1.0000`
- Recall: `1.0000`
- F1: `1.0000`

## Lead-Time / Delay
- First detection delay sec: `33.28748369216919`
- Mean detection delay sec: `76.65972557300475`
- Median detection delay sec: `80.11188316345215`

## SOM Runtime Metrics
- Training duration sec: `0.205`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.056`
- BMU coverage count: `73`
- Scored by phase: `{'chaos': 219, 'cooldown': 109, 'load': 0, 'normal': 1}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `219`
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
- `tier_a_cpu_usage_cores`: `36`
- `tier_a_memory_working_set_bytes`: `14`
- `tier_a_disk_read_bytes_per_sec`: `5`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776558712/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.