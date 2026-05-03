# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776731104`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `257.05`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776731121.35586, 'stop_ts': 1776731241.566871}`

## Detection Summary
- TP: `1`
- FP: `61`
- FN(proxy): `0`
- Precision: `0.0161`
- Recall: `1.0000`
- F1: `0.0317`

## Lead-Time / Delay
- First detection delay sec: `120.19589567184448`
- Mean detection delay sec: `120.19589567184448`
- Median detection delay sec: `120.19589567184448`

## SOM Runtime Metrics
- Training duration sec: `0.019`
- Bootstrap samples: `20`
- Avg scoring latency ms: `3.565`
- BMU coverage count: `45`
- Scored by phase: `{'chaos': 64, 'cooldown': 129, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `64`
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
- `tier_a_cpu_usage_cores`: `1`
- `tier_a_memory_working_set_bytes`: `1`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776731104/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.