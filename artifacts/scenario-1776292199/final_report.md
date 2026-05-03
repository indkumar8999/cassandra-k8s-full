# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776292199`
- Fault profile: `anomaly-concurrency-spike`
- Load profile: `high`
- Duration sec: `493.63`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776292422.62979, 'stop_ts': 1776292602.650507}`

## Detection Summary
- TP: `0`
- FP: `117`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.1`
- Bootstrap samples: `120`
- Avg scoring latency ms: `3.695`
- BMU coverage count: `65`
- Scored by phase: `{'normal': 152, 'load': 99, 'chaos': 295, 'cooldown': 120, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `295`
- Chaos min required: `50`
- Message: `ok`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `False`
- lead_time_present: `False`
- chaos_sample_gate_passed: `True`
- fp_within_limit: `False`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.