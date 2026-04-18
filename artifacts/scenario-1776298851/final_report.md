# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776298851`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `482.48`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776299064.06738, 'stop_ts': 1776299244.083222}`

## Detection Summary
- TP: `209`
- FP: `88`
- FN(proxy): `0`
- Precision: `0.7037`
- Recall: `1.0000`
- F1: `0.8261`

## Lead-Time / Delay
- First detection delay sec: `19.25907063484192`
- Mean detection delay sec: `82.29514776006269`
- Median detection delay sec: `82.16861867904663`

## SOM Runtime Metrics
- Training duration sec: `0.281`
- Bootstrap samples: `350`
- Avg scoring latency ms: `2.585`
- BMU coverage count: `51`
- Scored by phase: `{'normal': 1, 'load': 0, 'chaos': 294, 'cooldown': 146, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `294`
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
- `tier_b_simulator_writes_success_total`: `209`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776298851/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.