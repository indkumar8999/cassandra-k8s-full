# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-scaleout-demo-1776364185`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `709.89`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `4`
- Memory MB: `2048`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776364414.495417, 'stop_ts': 1776364834.520533}`

## Detection Summary
- TP: `239`
- FP: `0`
- FN(proxy): `0`
- Precision: `1.0000`
- Recall: `1.0000`
- F1: `1.0000`

## Lead-Time / Delay
- First detection delay sec: `16.765676021575928`
- Mean detection delay sec: `148.79977955479004`
- Median detection delay sec: `98.19815325737`

## SOM Runtime Metrics
- Training duration sec: `0.469`
- Bootstrap samples: `350`
- Avg scoring latency ms: `0.29`
- BMU coverage count: `18`
- Scored by phase: `{'normal': 1, 'load': 0, 'chaos': 514, 'cooldown': 2, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `514`
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
- `tier_b_simulator_writes_success_total`: `235`
- `tier_a_network_rx_bytes_per_sec__cassandra-1`: `4`
- `tier_a_disk_write_bytes_per_sec__cassandra-0`: `4`
- `tier_a_disk_write_bytes_per_sec__cassandra-1`: `2`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-scaleout-demo-1776364185/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.