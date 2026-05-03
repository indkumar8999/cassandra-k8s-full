# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776654352`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `425.31`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776654537.858753, 'stop_ts': 1776654717.8995788}`

## Detection Summary
- TP: `91`
- FP: `1`
- FN(proxy): `0`
- Precision: `0.9891`
- Recall: `1.0000`
- F1: `0.9945`

## Lead-Time / Delay
- First detection delay sec: `10.941596031188965`
- Mean detection delay sec: `49.474062521379075`
- Median detection delay sec: `35.30819344520569`

## SOM Runtime Metrics
- Training duration sec: `0.337`
- Bootstrap samples: `350`
- Avg scoring latency ms: `1.808`
- BMU coverage count: `75`
- Scored by phase: `{'chaos': 332, 'cooldown': 114, 'load': 0, 'normal': 2}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `332`
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
- `tier_a_disk_read_bytes_per_sec`: `75`
- `tier_a_cpu_usage_cores`: `17`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776654352/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.