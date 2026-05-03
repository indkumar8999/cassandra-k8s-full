# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776735250`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `256.11`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776735265.8832488, 'stop_ts': 1776735386.2210162}`

## Detection Summary
- TP: `0`
- FP: `82`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.035`
- Bootstrap samples: `20`
- Avg scoring latency ms: `5.908`
- BMU coverage count: `39`
- Scored by phase: `{'chaos': 0, 'cooldown': 85, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `False`
- Chaos scored samples: `0`
- Chaos min required: `50`
- Message: `chaos scored samples too low: 0 < 50`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `False`
- lead_time_present: `False`
- chaos_sample_gate_passed: `False`
- fp_within_limit: `False`

## Top Cause Metrics
- No cause hints were emitted.

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776735250/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.