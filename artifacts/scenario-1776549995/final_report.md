# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776549995`
- Fault profile: `anomaly-ttl-tombstone`
- Load profile: `high`
- Duration sec: `605.38`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776550181.190292, 'stop_ts': 1776550481.207972}`

## Detection Summary
- TP: `52`
- FP: `0`
- FN(proxy): `0`
- Precision: `1.0000`
- Recall: `1.0000`
- F1: `1.0000`

## Lead-Time / Delay
- First detection delay sec: `265.20340299606323`
- Mean detection delay sec: `278.7199149361023`
- Median detection delay sec: `278.66455245018005`

## SOM Runtime Metrics
- Training duration sec: `0.104`
- Bootstrap samples: `350`
- Avg scoring latency ms: `2.763`
- BMU coverage count: `76`
- Scored by phase: `{'chaos': 154, 'cooldown': 161, 'load': 0, 'normal': 0}`
- Dropped missing Tier A: `0`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `154`
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
- `tier_a_cpu_usage_cores`: `52`

## SOM artifacts (saved per run)
- Per-sample **normalized input vectors** are in `score_stream.json` under `input_vector` (same order as `feature_order` in `som_snapshot.json`).
- **SOM weights** (`weights`) and **area map** (`area_map`) are in `som_snapshot.json`.
- Snapshot JSON: `/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/scenario-1776549995/som_snapshot.json`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.