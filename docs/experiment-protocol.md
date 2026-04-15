# Cassandra UBL MVP Experiment Protocol

## Objective

Run reproducible online anomaly-detection experiments on distributed Cassandra with phases:

1. `normal`
2. `load`
3. `chaos`
4. `cooldown`

The learner is online after bootstrap training and continues scoring in real time.

## Prerequisites

- Kubernetes cluster with `cassandra-lab` namespace and at least 3 Ready worker nodes.
- Cassandra pods (`cassandra-0/1/2`) must be scheduled on distinct nodes.
- Cassandra and simulator deployed.
- Prometheus stack deployed and scraping:
  - Cassandra JMX (`cassandra-podmonitor.yaml`)
  - Simulator (`simulator-podmonitor.yaml`)
- Learner and chaos injector deployed.
- Context must not be `docker-desktop` or `kind` for final experiments.

## Mandatory Run Metadata

For each run store:

- run id
- timestamp
- cluster size and namespace
- simulator profile
- fault profile
- phase durations
- learner config (`SOM_*`, threshold percentile, smoothing, streak)
- image tags

## Fault Profiles (MVP)

- `memleak-like`
- `cpuhog-like`
- `network-congestion-like`
- `bottleneck-like`

Each run stores:

- fault profile version/name
- target selector/path
- injection intensity parameters
- commanded start/stop timestamps
- verified effective window timestamps
- reset verification timestamp

## Baseline + Ablation Matrix

### Baseline

- no fault (`normal/load/cooldown`)

### Fault runs

- one run per fault profile minimum

### Required ablations

- smoothing: off vs on (multiple `k`)
- threshold percentiles: `70/76/82/88/95`
- anomaly streak: `1/2/3`
- feature set:
  - Tier A only
  - Tier A + Tier B

## Metrics and Result Artifacts

Per run, collect:

- `run_summary.json`
- `run_events.json`
- `score_stream.json`
- `alarms.json`
- `learner_report.json`
- `simulator_metrics.json`
- `final_report.json`
- `final_report.md`

## Mid-Review Fix Mapping

- Training time + SOM performance -> `learner_report.json`, `final_report.md`
- Real system metrics (not proxy-only) -> Tier A mandatory Prometheus contract
- Real-time system behavior -> learner online loop after bootstrap
- Network framing -> profile name `network-congestion-like`
- Better experiment presentation -> ablation matrix + per-profile result reporting
