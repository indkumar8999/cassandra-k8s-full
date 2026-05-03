# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776738815`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `420.49`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776738995.6420748, 'stop_ts': 1776739115.795104}`

## Detection Summary
- TP: `2`
- FP: `0`
- FN(proxy): `0`
- Precision: `1.0000`
- Recall: `1.0000`
- F1: `1.0000`

## Lead-Time / Delay
- First detection delay sec: `67.31980443000793`
- Mean detection delay sec: `93.73267006874084`
- Median detection delay sec: `93.73267006874084`

## SOM Runtime Metrics
- Training duration sec: `0.345`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.14`
- BMU coverage count: `115`
- Scored by phase: `{'chaos': 177, 'cooldown': 200, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `177`
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
- `tier_a_disk_read_bytes_per_sec`: `2`
- `tier_a_memory_working_set_bytes`: `2`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776738815/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.