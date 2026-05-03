# Cassandra UBL Run Report

## Run Metadata
- Run ID: `scenario-ubl-b-1776209929`
- Fault profile: `bottleneck-like`
- Load profile: `high`
- Duration sec: `677.04`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776210276.80775, 'stop_ts': 1776210576.827958}`

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
- Training duration sec: `0.095`
- Bootstrap samples: `124`
- Avg scoring latency ms: `4.899`
- BMU coverage count: `15`

## Top Cause Metrics
- No cause hints were emitted.

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.