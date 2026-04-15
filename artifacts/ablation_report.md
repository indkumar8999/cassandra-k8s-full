# Cassandra UBL Ablation Report

- Runs root: `artifacts`
- Groups: `3`

## Group 1
- Config: fault=`bottleneck-like`, load=`high`, cpu_workers=`2`, mem_mb=`1024`, bottleneck_replicas=`2`
- Run count: `4`
- Median precision/recall/F1: `0.0` / `0.0` / `0.0`
- Median first detection delay sec: `None`
- Median training sec: `0.099`
- Median score latency ms: `5.173`
- Median BMU coverage: `12.5`
- Runs with TP / FP: `0` / `1`
- Run IDs: `scenario-1776206425, scenario-ubl-a-1776208744, scenario-ubl-b-1776209929, scenario-ubl-c-1776210608`

## Group 2
- Config: fault=`cpuhog-like`, load=`high`, cpu_workers=`2`, mem_mb=`1024`, bottleneck_replicas=`2`
- Run count: `1`
- Median precision/recall/F1: `0.0` / `0.0` / `0.0`
- Median first detection delay sec: `None`
- Median training sec: `0.071`
- Median score latency ms: `3.066`
- Median BMU coverage: `1.0`
- Runs with TP / FP: `0` / `0`
- Run IDs: `scenario-1776202265`

## Group 3
- Config: fault=`cpuhog-like`, load=`high`, cpu_workers=`4`, mem_mb=`1024`, bottleneck_replicas=`2`
- Run count: `1`
- Median precision/recall/F1: `0.0` / `0.0` / `0.0`
- Median first detection delay sec: `None`
- Median training sec: `0.07`
- Median score latency ms: `2.419`
- Median BMU coverage: `12.0`
- Runs with TP / FP: `0` / `1`
- Run IDs: `scenario-long-cpuhog-1776203008`
