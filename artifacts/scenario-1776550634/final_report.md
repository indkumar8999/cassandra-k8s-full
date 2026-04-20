# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776550634`
- Fault profile: `anomaly-ttl-tombstone`
- Load profile: `high`
- Duration sec: `605.31`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776550819.146752, 'stop_ts': 1776551119.164377}`

## Detection Summary
- TP: `69`
- FP: `1`
- FN(proxy): `0`
- Precision: `0.9857`
- Recall: `1.0000`
- F1: `0.9928`

## Lead-Time / Delay
- First detection delay sec: `2.6899678707122803`
- Mean detection delay sec: `162.2707563586857`
- Median detection delay sec: `68.94676280021667`

## SOM Runtime Metrics
- Training duration sec: `0.126`
- Bootstrap samples: `350`
- Avg scoring latency ms: `1.78`
- BMU coverage count: `111`
- Scored by phase: `{'chaos': 500, 'cooldown': 225, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `500`
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
- `tier_a_memory_working_set_bytes`: `67`
- `tier_a_cpu_usage_cores`: `52`
- `tier_a_disk_read_bytes_per_sec`: `46`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776550634/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.