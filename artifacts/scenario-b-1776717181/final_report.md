# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-b-1776717181`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `720.54`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776717602.172012, 'stop_ts': 1776717782.20945}`

## Detection Summary
- TP: `44`
- FP: `0`
- FN(proxy): `0`
- Precision: `1.0000`
- Recall: `1.0000`
- F1: `1.0000`

## Lead-Time / Delay
- First detection delay sec: `16.851818799972534`
- Mean detection delay sec: `120.62605321407318`
- Median detection delay sec: `136.43077266216278`

## SOM Runtime Metrics
- Training duration sec: `0.359`
- Bootstrap samples: `350`
- Avg scoring latency ms: `2.895`
- BMU coverage count: `235`
- Scored by phase: `{'chaos': 613, 'cooldown': 386, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `613`
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
- `tier_a_disk_read_bytes_per_sec`: `44`
- `tier_a_memory_working_set_bytes`: `32`
- `tier_a_cpu_usage_cores`: `12`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-b-1776717181/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.