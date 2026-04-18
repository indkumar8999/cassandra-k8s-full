# Cassandra UBL Run Report

## Run Metadata
- Run ID: `one-run-cpuhog-1776284545`
- Fault profile: `cpuhog-like`
- Load profile: `high`
- Duration sec: `371.3`

## Fault Injection Profile (EDA)
- Target namespace: `cassandra-lab`
- CPU workers: `2`
- Memory MB: `1024`
- Bottleneck replicas: `2`
- Commanded chaos window: `{'start_ts': 1776284737.0654368, 'stop_ts': 1776284857.077895}`

## Detection Summary
- TP: `190`
- FP: `104`
- FN(proxy): `0`
- Precision: `0.6463`
- Recall: `1.0000`
- F1: `0.7851`

## Lead-Time / Delay
- First detection delay sec: `8.419512033462524`
- Mean detection delay sec: `64.05683217676062`
- Median detection delay sec: `64.02314245700836`

## SOM Runtime Metrics
- Training duration sec: `0.101`
- Bootstrap samples: `120`
- Avg scoring latency ms: `3.908`
- BMU coverage count: `80`
- Scored by phase: `{'normal': 104, 'load': 100, 'chaos': 204, 'cooldown': 102, 'unknown': 0}`
- Dropped missing Tier A: `None`
- Dropped missing Tier B: `None`

## Run Quality Gate
- Passed: `True`
- Chaos scored samples: `204`
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
- `tier_a_disk_read_bytes_per_sec__cassandra-2`: `182`
- `tier_a_disk_write_bytes_per_sec__cassandra-0`: `8`

## Notes
- Precision/recall are run-level indicators intended for comparative ablations.
- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.