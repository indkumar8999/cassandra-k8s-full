# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776716252`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `693.45`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776716705.425584, 'stop_ts': 1776716825.628725}`

## Detection Summary
- TP: `98`
- FP: `27`
- FN(proxy): `0`
- Precision: `0.7840`
- Recall: `1.0000`
- F1: `0.8789`

## Lead-Time / Delay
- First detection delay sec: `24.673084497451782`
- Mean detection delay sec: `59.08769241401127`
- Median detection delay sec: `59.84019196033478`

## SOM Runtime Metrics
- Training duration sec: `0.365`
- Bootstrap samples: `350`
- Avg scoring latency ms: `4.738`
- BMU coverage count: `406`
- Scored by phase: `{'chaos': 227, 'cooldown': 508, 'load': 0, 'normal': 214}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `227`
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
- `tier_a_disk_read_bytes_per_sec`: `98`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776716252/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.