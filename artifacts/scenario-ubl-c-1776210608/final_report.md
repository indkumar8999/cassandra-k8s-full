# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-ubl-c-1776210608`
- Fault profile: `bottleneck-like`
- Load profile: `high`
- Duration sec: `680.28`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776210958.900654, 'stop_ts': 1776211258.917876}`

## Detection Summary
- TP: `0`
- FP: `0`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.097`
- Bootstrap samples: `126`
- Avg scoring latency ms: `5.005`
- BMU coverage count: `20`
- Scored by phase: `{'normal': 21, 'load': 22, 'chaos': 5, 'cooldown': 0, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `False`
- Chaos scored samples: `5`
- Chaos min required: `50`
- Message: `chaos scored samples too low: 5 < 50`

## Acceptance Criteria
- Passed: `False`
- Max FP allowed: `10`
- tp_during_chaos: `False`
- lead_time_present: `False`
- chaos_sample_gate_passed: `False`
- fp_within_limit: `True`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.