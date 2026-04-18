# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776297213`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `373.01`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776297496.343337, 'stop_ts': 1776297556.358916}`

## Detection Summary
- TP: `67`
- FP: `18`
- FN(proxy): `0`
- Precision: `0.7882`
- Recall: `1.0000`
- F1: `0.8816`

## Lead-Time / Delay
- First detection delay sec: `19.733144521713257`
- Mean detection delay sec: `39.73388292896214`
- Median detection delay sec: `39.84067153930664`

## SOM Runtime Metrics
- Training duration sec: `0.135`
- Bootstrap samples: `120`
- Avg scoring latency ms: `4.371`
- BMU coverage count: `61`
- Scored by phase: `{'normal': 51, 'load': 296, 'chaos': 100, 'cooldown': 49, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `100`
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
- `tier_a_disk_read_bytes_per_sec__cassandra-0`: `67`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776297213/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.