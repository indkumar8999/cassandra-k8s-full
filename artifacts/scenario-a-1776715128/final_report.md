# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-a-1776715128`
- Fault profile: `None`
- Load profile: `None`
- Duration sec: `692.49`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776715580.772927, 'stop_ts': 1776715700.864243}`

## Detection Summary
- TP: `1`
- FP: `30`
- FN(proxy): `0`
- Precision: `0.0323`
- Recall: `1.0000`
- F1: `0.0625`

## Lead-Time / Delay
- First detection delay sec: `89.40091586112976`
- Mean detection delay sec: `89.40091586112976`
- Median detection delay sec: `89.40091586112976`

## SOM Runtime Metrics
- Training duration sec: `0.198`
- Bootstrap samples: `816`
- Avg scoring latency ms: `3.182`
- BMU coverage count: `139`
- Scored by phase: `{'chaos': 225, 'cooldown': 245, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `225`
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
- `tier_a_disk_read_bytes_per_sec`: `1`
- `tier_a_cpu_usage_cores`: `1`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-a-1776715128/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.