# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776202265`
- Fault profile: `cpuhog-like`
- Load profile: `high`
- Duration sec: `466.78`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776202597.305265, 'stop_ts': 1776202687.320506}`

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
- Training duration sec: `0.071`
- Bootstrap samples: `120`
- Avg scoring latency ms: `3.066`
- BMU coverage count: `1`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.