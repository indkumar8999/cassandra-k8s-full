# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776734391`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `255.76`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776734407.1480498, 'stop_ts': 1776734527.299895}`

## Detection Summary
- TP: `110`
- FP: `96`
- FN(proxy): `0`
- Precision: `0.5340`
- Recall: `1.0000`
- F1: `0.6962`

## Lead-Time / Delay
- First detection delay sec: `24.260534524917603`
- Mean detection delay sec: `55.35239191922275`
- Median detection delay sec: `55.371870160102844`

## SOM Runtime Metrics
- Training duration sec: `0.051`
- Bootstrap samples: `20`
- Avg scoring latency ms: `2.984`
- BMU coverage count: `41`
- Scored by phase: `{'chaos': 142, 'cooldown': 115, 'load': 0, 'normal': 4}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `142`
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
- `tier_a_disk_read_bytes_per_sec`: `110`
- `tier_a_cpu_usage_cores`: `110`
- `tier_a_memory_working_set_bytes`: `110`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776734391/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.