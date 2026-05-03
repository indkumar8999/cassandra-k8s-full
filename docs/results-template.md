# Cassandra UBL Result Template

Use this template for each run profile and each ablation setting.

## Header

- Run ID:
- Timestamp:
- Fault profile:
- Phase durations:
- Feature set:
- Smoothing config:
- Threshold percentile:
- Anomaly streak:

## Detection Metrics

- TP:
- FP:
- FN (proxy):
- Precision:
- Recall:
- F1:

## Lead Time / Delay

- First detection delay (sec):
- Mean detection delay (sec):
- Median detection delay (sec):

## SOM Runtime Metrics

- Bootstrap training time (sec):
- Bootstrap sample count:
- Avg score latency (ms):
- Alarm decision latency (ms):
- BMU coverage:

## Fault Profile EDA

- Injection target:
- Injection intensity:
- Commanded window:
- Verified window:
- Recovery timestamp:

## Cause Ranking

- Top 1:
- Top 2:
- Top 3:

## Notes

- Observed behavior during `normal/load/chaos/cooldown`:
- Metric shifts in Tier A:
- Metric shifts in Tier B:
- Any run instability/issues:
