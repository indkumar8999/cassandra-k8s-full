# Cassandra UBL Run Report

## Run Metadata
- Run ID: `stress-ramp-b-spike`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `365.03`
- Simulator telemetry enabled: `None`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776457910.809508, 'stop_ts': 1776458030.8255858}`

## Detection Summary
- TP: `10`
- FP: `1`
- FN(proxy): `0`
- Precision: `0.9091`
- Recall: `1.0000`
- F1: `0.9524`

## Lead-Time / Delay
- First detection delay sec: `7.682490110397339`
- Mean detection delay sec: `13.348990225791932`
- Median detection delay sec: `14.76874327659607`

## SOM Runtime Metrics
- Training duration sec: `0.211`
- Bootstrap samples: `350`
- Avg scoring latency ms: `3.109`
- BMU coverage count: `29`
- Scored by phase: `{'chaos': 33, 'cooldown': 44, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `False`
- Chaos scored samples: `33`
- Chaos min required: `50`
- Message: `chaos scored samples too low: 33 < 50`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `True`
- lead_time_present: `True`
- chaos_sample_gate_passed: `False`
- fp_within_limit: `True`

## Top Cause Metrics
- `tier_a_disk_read_bytes_per_sec`: `10`
- `tier_a_memory_working_set_bytes`: `10`
- `tier_a_cpu_usage_cores`: `10`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/stress-ramp-b-spike/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.
- Simulator telemetry status: `telemetry-disabled`
- Simulator telemetry note: `Simulator metrics not required for stress-only mode.`