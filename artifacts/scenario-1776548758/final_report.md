# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776548758`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `455.65`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776548943.848171, 'stop_ts': 1776549124.09236}`

## Detection Summary
- TP: `7`
- FP: `24`
- FN(proxy): `0`
- Precision: `0.2258`
- Recall: `1.0000`
- F1: `0.3684`

## Lead-Time / Delay
- First detection delay sec: `26.837757349014282`
- Mean detection delay sec: `54.861090251377654`
- Median detection delay sec: `74.6940758228302`

## SOM Runtime Metrics
- Training duration sec: `0.131`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.869`
- BMU coverage count: `68`
- Scored by phase: `{'chaos': 329, 'cooldown': 150, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `329`
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
- `tier_a_memory_working_set_bytes`: `7`
- `tier_a_cpu_usage_cores`: `7`
- `tier_a_disk_read_bytes_per_sec`: `4`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776548758/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.