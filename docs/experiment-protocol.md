# Cassandra UBL MVP Experiment Protocol

## Objective

Run reproducible online anomaly-detection experiments on distributed Cassandra.

### End-to-end story (phases A–E)

Use this framing for demos and write-ups; it maps cleanly onto the services even though the stock orchestrator only automates part of it.

| Phase | Intent | Where it lives |
| --- | --- | --- |
| **A** | Baseline + bootstrap until UBL is **ready** (SOM trained, scoring valid). | Orchestrator waits on learner `GET /status` (`ready: true`) while simulator + optional bootstrap fault run; learner phase `normal`. |
| **B** | High load + fault injection (stress window). | Orchestrator sets target simulator profile, learner phase `chaos`, chaos `POST /start_fault`, hold for `chaos_sec`. |
| **C** | Early anomaly signal + lead time. | Learner `GET /alarms`, `GET /report` (`lead_time_seconds`, alarms vs chaos start); reporting `final_report.*`. |
| **D** | **Mitigation** (capacity): hot spare worker ready, scale Cassandra **3 → 4** so `cassandra-3` schedules and joins the ring. | **Manual / kubectl** or [`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) (waits for a **new** chaos-phase alarm by default — avoids scaling on stale `/alarms`). Not performed by `orchestrator/run_scenario.py`. |
| **E** | **Recovery evidence**: ring stable, tail latency stops worsening; argue **no SLO breach** (or breach avoided) using the same Grafana/Prometheus views as during B–C. | **Observability** (dashboards you define); optional narrative in run notes. |
| **F** | **Return to steady capacity**: SLO signal **continuously OK** (hysteresis), then scale **4 → 3**; hot spare worker stays Ready. | Same script as **D**: [`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) runs scale-out then Prometheus-gated scale-in. Demo-grade: not a substitute for `nodetool decommission` in production. |

### Learner phase labels (artifact contract)

Reports and gates still bucket samples by learner-reported phase names:

1. `normal`
2. `load` (legacy / optional soak; not required by the current orchestrator path)
3. `chaos`
4. `cooldown`

The learner is online after bootstrap training and continues scoring in real time.

## Prerequisites

- Kubernetes cluster with `cassandra-lab` namespace and at least **3** Ready worker nodes (strict MVP).
- For **phase D** scale-out demos: a **fourth** Ready worker (hot spare, e.g. `w4`) and headroom so a fourth Cassandra pod (`cassandra-3`) can become Ready without starving monitoring. Default Cassandra `resources.requests` in `k8s/cassandra/cassandra-statefulset.yaml` are sized so Tier‑A utilization is visible on **2 vCPU / ~4GiB** workers; optional **2GiB/VM** Multipass rebuild (`make rebuild-multipass-pressure`) increases fractional pressure further (OOM risk).
- Cassandra pods (`cassandra-0/1/2`) must be scheduled on distinct nodes (before scale-out); after `replicas: 4`, enforce your own anti-affinity / placement checks if the demo requires one pod per worker.
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

Aligned with chaos-injector `POST /start_fault` (see `chaos-injector/main.py`):

- `baseline-normal`
- `anomaly-hot-partition`, `anomaly-compaction-pressure`, `anomaly-concurrency-spike`, `anomaly-ttl-tombstone`, `anomaly-mixed-skew-large-payload`
- `network-congestion-like`, `bottleneck-like`
- Aliases: `cpuhog-like` (maps to concurrency spike), `memleak-like` (maps to compaction pressure)

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

## Run Quality Gate (Required)

Each run must pass data-quality checks before model metrics are trusted:

- Chaos scored samples must be at least `50` (default gate).
- Reports include explicit counters for:
  - dropped samples due to missing Tier A
  - dropped samples due to missing Tier B fallback failure
  - scored samples by phase (`normal/load/chaos/cooldown`)

CLI (single run):

```bash
python3 ./reporting/generate_report.py --run-dir <run_dir> --chaos-min-scored 50 --fail-on-quality-gate
```

## Acceptance Criteria ("Good" Run)

Use these acceptance checks for tuning batches:

1. At least one TP during chaos window.
2. Lead time is present (`first_detection_delay_sec` is not null).
3. Chaos sample gate passes.
4. False positives remain within configured limit (`--max-fp`, default `10`).

### Optional: mitigation + recovery (D + E + F)

When presenting a closed-loop story, capture in run metadata or a short addendum:

- Timestamp when Cassandra StatefulSet replicas went from 3 to 4 and when `cassandra-3` reached Ready.
- Ring / ops view after join (e.g. `nodetool status` equivalent or your Grafana panels).
- The SLO panels you use (p99 latency, errors, etc.) **before mitigation, at alarm, and after ring stabilizes** so “no violation” or “violation avoided” is tied to data, not narration alone.
- **Scale-in (F):** the PromQL query, threshold, comparison mode (`lt`/`gt`/…), and how long the metric stayed in the OK band before scaling to baseline replicas (see `cassandra_elastic_replicas.sh` env vars). Log when replicas returned to **3** while **w4** (or equivalent) remained Ready as the spare.

## Mid-Review Fix Mapping

- Training time + SOM performance -> `learner_report.json`, `final_report.md`
- Real system metrics (not proxy-only) -> Tier A mandatory Prometheus contract
- Real-time system behavior -> learner online loop after bootstrap
- Network framing -> profile name `network-congestion-like`
- Better experiment presentation -> ablation matrix + per-profile result reporting
