# Cassandra UBL Run Report

## Run Metadata
- Run ID: `stress-ramp-s2-cpu-v2`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `523.54`
- Simulator telemetry enabled: `None`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776461886.437509, 'stop_ts': 1776462066.454926}`

## Detection Summary
- TP: `125`
- FP: `1`
- FN(proxy): `0`
- Precision: `0.9921`
- Recall: `1.0000`
- F1: `0.9960`

## Lead-Time / Delay
- First detection delay sec: `1.1180686950683594`
- Mean detection delay sec: `65.59551755523681`
- Median detection delay sec: `33.84639596939087`

## SOM Runtime Metrics
- Training duration sec: `0.023`
- Bootstrap samples: `533`
- Avg scoring latency ms: `1.556`
- BMU coverage count: `33`
- Scored by phase: `{'chaos': 130, 'cooldown': 43, 'load': 0, 'normal': 3}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `130`
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
- `tier_a_disk_read_bytes_per_sec`: `125`
- `tier_a_cpu_usage_cores`: `93`
- `tier_a_memory_working_set_bytes`: `74`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/stress-ramp-s2-cpu-v2/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.
- Simulator telemetry status: `telemetry-disabled`
- Simulator telemetry note: `Simulator metrics not required for stress-only mode.`