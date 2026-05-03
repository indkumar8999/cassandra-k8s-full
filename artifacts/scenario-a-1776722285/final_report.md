# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776722285`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `702.3`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776722747.4490461, 'stop_ts': 1776722867.5678961}`

## Detection Summary
- TP: `223`
- FP: `163`
- FN(proxy): `0`
- Precision: `0.5777`
- Recall: `1.0000`
- F1: `0.7323`

## Lead-Time / Delay
- First detection delay sec: `0.49803876876831055`
- Mean detection delay sec: `60.72135331598633`
- Median detection delay sec: `60.85572266578674`

## SOM Runtime Metrics
- Training duration sec: `0.026`
- Bootstrap samples: `693`
- Avg scoring latency ms: `4.728`
- BMU coverage count: `135`
- Scored by phase: `{'chaos': 242, 'cooldown': 343, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `242`
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
- `tier_a_disk_read_bytes_per_sec`: `223`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776722285/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.