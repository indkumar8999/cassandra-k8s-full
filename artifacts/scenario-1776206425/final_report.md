# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-1776206425`
- Fault profile: `bottleneck-like`
- Load profile: `high`
- Duration sec: `700.8`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776206795.870132, 'stop_ts': 1776207035.888314}`

## Detection Summary
- TP: `0`
- FP: `20`
- FN(proxy): `1`
- Precision: `0.0000`
- Recall: `0.0000`
- F1: `0.0000`

## Lead-Time / Delay
- First detection delay sec: `None`
- Mean detection delay sec: `None`
- Median detection delay sec: `None`

## SOM Runtime Metrics
- Training duration sec: `0.101`
- Bootstrap samples: `120`
- Avg scoring latency ms: `5.788`
- BMU coverage count: `10`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.