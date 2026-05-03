# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-long-cpuhog-1776203008`
- Fault profile: `cpuhog-like`
- Load profile: `high`
- Duration sec: `691.79`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `4`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776203370.030485, 'stop_ts': 1776203610.0486221}`

## Detection Summary
- TP: `0`
- FP: `1`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.07`
- Bootstrap samples: `120`
- Avg scoring latency ms: `2.419`
- BMU coverage count: `12`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.