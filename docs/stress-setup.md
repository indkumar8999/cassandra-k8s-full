# Stress Setup (NoSQLBench-First)

Author: Aum Pandya ([apandya4@ncsu.edu](mailto:apandya4@ncsu.edu))

This document is the implementation guide for the stress path.
It is focused on **NoSQLBench-based stress injection**.
It explains how this repository actually runs stress in Kubernetes.

This is technical documentation for developers.
It does not discuss experiment outcomes.

## Scope

This guide is based on:

- `chaos-injector/main.py`
- `k8s/chaos-injector/chaos-injector-deployment.yaml`
- `k8s/chaos-injector/chaos-injector-service.yaml`
- `k8s/chaos-injector/chaos-injector-rbac.yaml`
- `k8s/chaos-injector/chaos-nosqlbench-scenarios-configmap.yaml`
- `k8s/chaos-injector/nosqlbench-histostats-exporter-configmap.yaml`
- `k8s/chaos-injector/nosqlbench-histostats-pvc.yaml`
- project report (`ADS_Project_Final_Report.pdf`) methodology and architecture sections

## Why NoSQLBench Here

The report describes stress injection as NoSQLBench-driven Kubernetes Jobs.
In this repository, that path is implemented through the `POST /start_nosqlbench` API.

High-level behavior:

1. caller sends profile + options to `chaos-injector`
2. injector selects NoSQLBench scenario YAML
3. injector creates one or more Kubernetes Jobs
4. each Job runs NoSQLBench with profile parameters
5. metrics are exported through push and/or histostat sidecar paths
6. caller stops profile with `POST /stop_nosqlbench` or `POST /reset_all`

## End-to-End NoSQLBench Flow

The report explains an eight-step NoSQLBench path.
The implementation maps like this:

1. **Orchestration command**
  Typically from `orchestrator/run_scenario_nosqlbench.py` or direct API calls.
2. **Profile dispatch**
  `main.py` route `POST /start_nosqlbench` parses `profile`.
3. **YAML scenario mapping**
  Profile maps to one of the files in `chaos-nosqlbench-scenarios` ConfigMap.
4. **Parallel Jobs**
  `_start_nb_parallel_jobs()` creates `J` Jobs (`parallel_jobs`) with unique names.
5. **NoSQLBench command build**
  `_nb_cmd_file_workload()` builds args: hosts, keyspace, rf, cycles, threads, push args.
6. **Traffic to Cassandra**
  Jobs use Cassandra service hosts and local DC (`CASSANDRA_LOCAL_DC`).
7. **Metrics export**
  - Push path via `PROMPUSH_URL` (Victoria import URL expansion)
  - Histostat path via PVC + exporter sidecar at `/metrics` (9406)
8. **Cleanup and stop**
  `_stop_nosqlbench_fault()` deletes jobs and updates fault record state.

## Runtime APIs (What You Actually Call)

Base URL after port-forward:

- `http://localhost:8200`

Primary endpoints:

- `GET /health`
- `GET /faults`
- `POST /start_nosqlbench`  <- primary stress start path
- `POST /stop_nosqlbench`
- `POST /reset_all`

Legacy-compatible endpoints still exist:

- `POST /start_fault`
- `POST /stop_fault`

Use `start_nosqlbench` for current workflows.

### Minimal API examples

Start baseline:

```bash
curl -sS -X POST "http://localhost:8200/start_nosqlbench" \
  -H "Content-Type: application/json" \
  -d '{"profile":"baseline-normal","duration_sec":60}'
```

Stop baseline:

```bash
curl -sS -X POST "http://localhost:8200/stop_nosqlbench" \
  -H "Content-Type: application/json" \
  -d '{"profile":"baseline-normal"}'
```

Show active profiles:

```bash
curl -sS "http://localhost:8200/faults"
```

Hard reset all active faults:

```bash
curl -sS -X POST "http://localhost:8200/reset_all"
```

## Valid NoSQLBench Profiles (in main.py)

`main.py` defines these valid NoSQLBench profile names:

- `baseline-normal`
- `anomaly-hot-partition`
- `anomaly-compaction-pressure`
- `anomaly-concurrency-spike`
- `anomaly-ttl-tombstone`
- `anomaly-mixed-skew-large-payload`
- `anomaly-university-memory-pressure`
- `anomaly-memory-pressure`
- `short-cpu-spike`
- `network-congestion-like`
- `bottleneck-like`
- compatibility aliases: `cpuhog-like`, `memleak-like`

## Profile -> Scenario File Mapping

In `main.py`, profile handlers map to these scenario files:

- `baseline-normal` -> `baseline_normal.yaml`
- `anomaly-hot-partition` -> `hot_partition.yaml`
- `anomaly-compaction-pressure` -> `compaction_pressure.yaml`
- `anomaly-concurrency-spike` -> `concurrency_spike.yaml`
- `anomaly-mixed-skew-large-payload` -> `mixed_skew.yaml`
- `anomaly-ttl-tombstone` -> `ttl_write.yaml` then `ttl_read.yaml`
- `anomaly-university-memory-pressure` -> `university_heavy.yaml`
- `anomaly-memory-pressure` -> `memory_pressure.yaml`

Special cases:

- `short-cpu-spike` runs in-pod exec CPU burn logic (not NB file workload)
- `network-congestion-like` uses NetworkPolicy behavior
- `bottleneck-like` patches Cassandra replicas

## NoSQLBench Profile Implementation (Very Detailed)

This section explains **exactly** how profile behavior is encoded.
It uses the ConfigMap content and report stress-family descriptions.

### Common execution template used by most profiles

Most scenarios follow this sequence:

1. `schema` block
  - create keyspace with `SimpleStrategy`
  - replication factor uses template `rf` (default 3)
2. `rampup` block
  - warm-up writes
  - `LOCAL_ONE` consistency
3. `main` block
  - steady stress phase
  - profile-specific read/write ratio, payload shape, and key distribution

Main runtime values are passed from `main.py`:

- `hosts`
- `localdc`
- `keyspace`
- `rf`
- `main-cycles`
- `rampup-cycles`
- `threads`

### `baseline_normal.yaml`

Purpose:

- balanced baseline traffic

Implementation details:

- read and write blocks are both active (`main-read`, `main-write`)
- ratios default to `read_ratio=5`, `write_ratio=5`
- keys are hashed over broad range (`Mod(1000000)`)
- payload is string-like hashed content

How `main.py` drives it:

- handler: `_nb_start_baseline_normal`
- optional request fields: `duration_sec`, `threads`, `replication_factor`, `read_ratio`, `write_ratio`
- per-parallel-job table names are suffixed (`table=nbbase_<job-index>`)

### `hot_partition.yaml`

Purpose:

- force concentration on one partition key

Implementation details:

- partition key is fixed (`pk: FixedValue('HOT')`)
- clustering key is high-cardinality hash
- write-only main phase

How `main.py` drives it:

- handler: `_nb_start_anomaly_hot_partition`
- file workload: `hot_partition.yaml`
- default thread count follows hot profile defaults in `main.py`

### `compaction_pressure.yaml`

Purpose:

- increase compaction work and write amplification

Implementation details:

- table uses `(pk, c1)` primary key shape
- payload uses larger textual form (`NumberNameToString`)
- write-heavy pressure pattern

How `main.py` drives it:

- handler: `_nb_start_anomaly_compaction_pressure`
- supports `pop_end` style tuning in request
- ramp-up cycles are bounded with a safety formula in code

### `concurrency_spike.yaml`

Purpose:

- aggressive write concurrency pressure

Implementation details:

- very large keyspace hash ranges
- high cycle volume
- write-only main phase

How `main.py` drives it:

- handler: `_nb_start_anomaly_concurrency_spike`
- default thread values are high and can be overridden by request

### `mixed_skew.yaml`

Purpose:

- mixed read/write with skew and variable payload

Implementation details:

- read ratio `3`, write ratio `7`
- partition distribution intentionally narrower than baseline
- read queries use higher row limit (`limit 50`)

How `main.py` drives it:

- handler: `_nb_start_anomaly_mixed_skew_large_payload`
- scenario file: `mixed_skew.yaml`

### TTL pair: `ttl_write.yaml` + `ttl_read.yaml`

Purpose:

- tombstone-oriented two-phase behavior

Implementation details:

1. phase A writes rows with `USING TTL <<ttlsec>>`
2. phase B reads after delay window

How `main.py` drives it:

- handler: `_nb_start_anomaly_ttl_tombstone`
- builds one chained script:
  - run write workload
  - `sleep delay_sec`
  - run read workload
- request supports `ttl_sec`, `delay_sec`, `write_threads`, `read_threads`

### `university_heavy.yaml`

Purpose:

- heavy mixed profile used as substitute for older user-profile path

Implementation details:

- read/write mixed blocks with ratio `4` / `6`
- moderate key concentration with larger semantic payload style

How `main.py` drives it:

- handler: `_nb_start_anomaly_university_memory_pressure`
- forces `parallel_jobs=1` in code to avoid startup races

### `memory_pressure.yaml`

Purpose:

- memory-biased writes with large blob payloads

Implementation details:

- payload uses `ByteBufferSizedHashed(TEMPLATE(payload_size,262144))`
- schema is compact and write-focused
- default run block uses templated thread control

How `main.py` drives it:

- handler: `_nb_start_anomaly_memory_pressure`
- profile value exposed as `anomaly-memory-pressure`

### Report profile family mapping

The report stress families map to this implementation as:

- baseline normal -> `baseline-normal`
- short CPU spike -> `short-cpu-spike` (non-NB in-pod exec helper)
- CPU pressure/write spike -> `anomaly-concurrency-spike`
- disk pressure/large payload -> `anomaly-compaction-pressure` and mixed variants
- memory pressure/concentrated keys -> `anomaly-memory-pressure` or university-heavy path

## Deep Dive: Scenario ConfigMap Structure

File: `k8s/chaos-injector/chaos-nosqlbench-scenarios-configmap.yaml`

Every NoSQLBench scenario follows a similar pattern:

- `description`: human summary
- `scenarios`: execution entry points (`schema`, `rampup`, `main`)
- `bindings`: generated value functions (keys, payload, time)
- `blocks`: concrete CQL operations

Common block pattern:

1. `schema` creates keyspace/table (`rf` templated)
2. `rampup` warms workload
3. `main` executes read/write pressure pattern

Important examples:

- `baseline_normal.yaml`: balanced read/write
- `hot_partition.yaml`: single hot key writes
- `compaction_pressure.yaml`: wider rows / heavier write structure
- `concurrency_spike.yaml`: high write pressure and thread volume
- `mixed_skew.yaml`: mixed read/write + skew
- `ttl_write.yaml` + `ttl_read.yaml`: tombstone lifecycle path
- `university_heavy.yaml`: heavy mixed pattern
- `memory_pressure.yaml`: larger payload and memory-biased write path

## Orchestrator Integration 

Primary script:

- `orchestrator/run_scenario_nosqlbench.py`

This script is the end-to-end coordinator for NoSQLBench stress runs.
In this section we only describe learner and chaos behavior.

### What orchestrator does for stress lifecycle

1. checks service health for required endpoints
2. resets learner and chaos state
3. starts bootstrap NoSQLBench fault profile (`/start_nosqlbench`)
4. waits for learner readiness (`/status`)
5. stops bootstrap profile
6. sets learner to chaos phase (`/phase`)
7. optionally starts extra fault (`/start_fault`, e.g. `short-cpu-spike`)
8. starts anomaly NoSQLBench profile (`/start_nosqlbench`)
9. sleeps for chaos duration
10. stops anomaly profile
11. sets learner to cooldown phase
12. collects learner score stream, alarms, report, and writes run artifacts

### Key orchestrator arguments for stress behavior

- `--bootstrap-fault-profile`
- `--fault-profile`
- `--chaos-sec`
- `--cooldown-sec`
- `--bootstrap-timeout-sec`
- `--nb-threads`
- `--nb-parallel-jobs`
- `--bootstrap-nb-threads`
- `--bootstrap-nb-parallel-jobs`
- `--start-fault-profile`
- `--start-fault-duration-sec`
- `--start-fault-target-mode`
- `--start-fault-target-pod`

### Run artifacts produced by orchestrator

Inside `./artifacts/<run-id>/` it writes:

- `run_summary.json`
- `run_events.json`
- `learner_report.json`
- `score_stream.json`
- `alarms.json`
- `som_snapshot.json`

Optional report generation is called from the script unless `--skip-report` is used.

## Legacy Cassandra-Stress Implementation (Detailed)

This repository still contains a full legacy path in `chaos-injector/main.py`.
It is not the preferred path, but it is important to document.

### Legacy API path

- start: `POST /start_fault`
- stop: `POST /stop_fault`

This path stores active entries in `ACTIVE_FAULTS`.
NoSQLBench path uses `ACTIVE_NB_FAULTS`.

### Core cassandra-stress config in code

Key variables:

- `CASSANDRA_STRESS_CONTACT_POINT`
- `CASSANDRA_STRESS_PORT`
- `CASSANDRA_STRESS_BIN` (`/opt/cassandra/tools/bin/cassandra-stress`)
- `CASSANDRA_STRESS_CL`
- stress job resource requests/limits
- per-profile default threads (`DEFAULT_CASSANDRA_STRESS_`*)

### Legacy command builder model

The legacy path builds concrete `cassandra-stress` command arrays.
Main helper:

- `_cassandra_stress_base_args()`

It injects:

- duration
- consistency
- node/port
- rate threads
- population sequence
- schema replication factor
- column distribution settings
- 1-second log interval to stdout

### Legacy per-profile command functions

Implemented functions include:

- `_cmd_baseline_normal` (`mixed ratio(write=5,read=5)`)
- `_cmd_anomaly_hot_partition` (`write`)
- `_cmd_anomaly_compaction_pressure` (`write`, larger row shape)
- `_cmd_anomaly_concurrency_spike` (`write`, high threads)
- `_cmd_anomaly_mixed_skew_large_payload` (`mixed ratio(write=7,read=3)`)
- `_cmd_anomaly_ttl_tombstone_script` (two-phase write+read chain)
- `_cmd_anomaly_university_memory_pressure` (`user` profile from mounted YAML)

### Legacy university user profile path

Files:

- `chaos-injector/university-profile.yaml`
- ConfigMap name: `chaos-university-stress-profile` (mounted by job build path)

Implementation note:

- for this profile, code mounts `/profiles/university-profile.yaml`
- command uses `cassandra-stress user profile=/profiles/university-profile.yaml`
- code forces `parallel_jobs=1` to avoid startup race with truncate/init

### Legacy job creation behavior

Function:

- `_start_cassandra_stress_job()`

Behavior:

- resolves `parallel_jobs`
- creates one or more Kubernetes Jobs
- labels jobs with profile
- stores command and job names in fault record
- returns running `FaultRecord`

### Legacy stop behavior

Function:

- `_stop_fault()`

Behavior:

- for stress profiles: delete created jobs
- for network profile: delete network policy
- for bottleneck profile: restore original Cassandra replicas

### Why legacy path is still present

Reason:

- backward compatibility for existing scripts and profile names
- transition support while NoSQLBench became the primary metrics-friendly path

Developer rule:

- prefer `/start_nosqlbench` for new workflows
- keep `/start_fault` only when legacy compatibility is required

## Deployment Details (chaos-injector)

File: `k8s/chaos-injector/chaos-injector-deployment.yaml`

Key implementation details:

- ServiceAccount: `chaos-injector`
- Namespace: `cassandra-lab`
- Pod port: `8200`
- Node affinity pins injector to `control-node`

Key env vars for NoSQLBench:

- `NOSQLBENCH_IMAGE`
- `NOSQLBENCH_JAVA_BIN`
- `NOSQLBENCH_JAR_PATH`
- `NOSQLBENCH_JAVA_OPTS`
- `NOSQLBENCH_WORKDIR`
- `NOSQLBENCH_SCENARIO_CONFIGMAP`
- `CASSANDRA_LOCAL_DC`

Metrics-related env vars:

- `PROMPUSH_URL` (Victoria push import style)
- `NOSQLBENCH_HISTOSTATS_ENABLED`
- `NOSQLBENCH_HISTOSTATS_INTERVAL`
- `NOSQLBENCH_HISTOSTATS_PVC`
- `NOSQLBENCH_HISTOSTATS_EXPORTER_CONFIGMAP`

Operational resource limits:

- `STRESS_JOB_CPU_REQUEST`, `STRESS_JOB_CPU_LIMIT`
- `STRESS_JOB_MEM_REQUEST`, `STRESS_JOB_MEM_LIMIT`
- `DEFAULT_STRESS_PARALLEL_JOBS`

## Service and RBAC

### Service

File: `k8s/chaos-injector/chaos-injector-service.yaml`

- ClusterIP service name: `chaos-injector`
- Port: `8200`

### RBAC

File: `k8s/chaos-injector/chaos-injector-rbac.yaml`

Injector Role allows:

- pods get/list/watch + pod logs/exec operations
- jobs create/get/list/watch/delete
- statefulset patch (for bottleneck profile)
- networkpolicy create/get/list/watch/delete
- services read access

This is required for profile orchestration behavior in `main.py`.

## Histostat Export Path

Files:

- `k8s/chaos-injector/nosqlbench-histostats-pvc.yaml`
- `k8s/chaos-injector/nosqlbench-histostats-exporter-configmap.yaml`

How it works:

1. NB job writes `hdrstats.csv` per job folder on mounted PVC
2. Sidecar exporter Python script reads latest CSV rows
3. Exporter publishes gauges on `/metrics` (port 9406)
4. Metrics include `p95` and `p99` in ns and ms
5. Labels include tag, job, and profile context

Why this matters:

- this gives structured client-latency metrics for SLO checks
- avoids fragile log parsing workflows

## SLO metrics

This section explains **what** SLO means in the report and **how** this repo turns stress into measurable SLO signals.
It uses simple definitions.
It does **not** interpret experiment outcomes.

### What “SLO” means here

In the report methodology, SLO is not a vague “health score”.
It is a rule on **client-side latency percentiles** for the workload **execute path**.

Typical signals:

- **p95 latency** in milliseconds
- **p99 latency** in milliseconds

These are **external** to Cassandra JVM tuning.
They describe what a client workload experiences under load.

### Instantaneous breach rule (from the report)

Let `p95(t)` be the scraped **p95** value at time `t` (milliseconds).

Let `theta` be the **SLO threshold** in milliseconds (a fixed policy number you choose).

The report uses an **instantaneous** breach indicator:

- if `p95(t) > theta` then the system is in breach at that scrape time
- otherwise it is not in breach at that scrape time

The report gives **200 ms** as the nominal threshold `theta` used in their methodology.
In your lab you may keep 200 ms or set another value.
The math is the same.

**p99** is tracked the same way in spirit (compare `p99(t)` to a threshold if you define one).
The report text emphasizes **p95** for the main breach rule example.

### Why client percentiles matter for this project

The report stresses two ideas:

1. **Client-visible harm** is what operators care about for latency SLOs.
2. **Structured latency series** are easier to scrape and align than parsing `cassandra-stress` text logs.

That is why NoSQLBench + metrics export is the preferred instrumentation path.

### End-to-end signal path (stress to SLO time series)

This matches the report’s “stress injection and SLO instrumentation” story and the repo wiring:

1. **Stress runs** as NoSQLBench inside Kubernetes Jobs.
2. NoSQLBench records latency histograms over time (**HDR histostats**).
3. Histostats are written on disk (PVC path) and/or pushed to metrics backends.
4. A **sidecar exporter** reads the latest histostat rows and exposes Prometheus text at `/metrics`.
5. **Prometheus** scrapes those series on an interval.
6. You query Prometheus for `p95` / `p99` as instant vectors or ranges.
7. Downstream scripts compare those values to `theta`.

### Repo implementation: histostat exporter metrics

File:

- `k8s/chaos-injector/nosqlbench-histostats-exporter-configmap.yaml`

The exporter emits gauges including:

- `nosqlbench_histostat_p95_ms` and `nosqlbench_histostat_p99_ms`
- also nanosecond variants (`*_ns`) because NoSQLBench records in ns internally

Important label behavior:

- the CSV `Tag` field is normalized (for example `Tag=execute` becomes tag label `execute`)
- job and profile labels are attached when available

This is the clean “structured percentile” path the report describes.

### Repo implementation: Victoria push path (`PROMPUSH_URL`)

File:

- `k8s/chaos-injector/chaos-injector-deployment.yaml`

`chaos-injector` sets `PROMPUSH_URL` so NoSQLBench can push metrics using a supported ingestion URL shape.

`main.py` logs whether `PROMPUSH_URL` is configured at startup.
If it is missing, NoSQLBench jobs may still run, but **push-based client metric export may be disabled**.

### Default PromQL used for SLO scraping in offline collection

File:

- `offline-training/collect_prometheus_samples.py`

Defaults (unless you override env vars):

- threshold: `NB_SLO_THRESHOLD_MS` default **200.0**
- p95 query: `max(nosqlbench_histostat_p95_ms{tag="execute"})`
- p99 query: similar pattern for p99

Each collected tick can include a JSON `slo` object with:

- `p95_ms`, `p99_ms`
- `threshold_ms`
- `slo_violated` boolean derived from `p95_ms > threshold_ms`

This is the repo’s concrete implementation of the report’s breach rule on scraped `p95`.

### Operational alignment rules (so SLO is meaningful)

SLO lines only make sense if you align clocks and phases:

1. **Stress window boundaries** must be explicit (`start` / `stop`).
2. **Prometheus scrape interval** must be known (stack may scrape at 1s in lab values).
3. **Query choice** must match your label set (`tag="execute"` is the default assumption in collector defaults).
4. **Parallel jobs** can create multiple series; `max(...)` is a simple aggregate policy, not the only valid policy.

### Grafana usage

The report describes dashboards that overlay:

- infra saturation time series
- client latency percentiles from stress tools
- phase markers for scenario transitions

In practice you point Grafana at Prometheus and/or Victoria depending where your NB series live.

### Formal evaluation window semantics (definitions only)

Later report sections define evaluation constructs like a **pending window** `W` used when pairing alarms with SLO breach events.

This stress doc does not compute those metrics.
It only states:

- you need clean `p95(t)` (or equivalent) time series
- you need breach timestamps derived from the rule `p95(t) > theta`
- you need alarm timestamps from the learner

Downstream tooling uses those aligned timelines.

### Practical checklist before trusting SLO numbers

1. Confirm NoSQLBench jobs are running and producing histostat files.
2. Confirm exporter `/metrics` responds on the forwarded port (if you port-forward a job pod).
3. Confirm Prometheus can scrape the target and the metric name exists.
4. Confirm your PromQL matches your label reality (`tag`, `nb_job`, etc.).
5. Confirm `theta` matches your lab policy (200 ms is only the report’s example nominal value).

## Recommended End-to-End Run Sequence (NoSQLBench Path)

From `cassandra/`:

1. Deploy:

```bash
bash ./scripts/deploy_strict_order.sh
```

1. Port-forward chaos/learner/monitoring endpoints as needed.
2. Run NoSQLBench scenario runner:

```bash
python3 orchestrator/run_scenario_nosqlbench.py --output-dir ./artifacts --fault-profile baseline-normal
```

1. Generate report artifacts:

```bash
python3 ./reporting/generate_report.py --run-dir "$(ls -dt ./artifacts/* | head -1)"
```

## Practical Debug Commands

Check chaos pod:

```bash
kubectl -n cassandra-lab get pods -l app=chaos-injector -o wide
kubectl -n cassandra-lab logs -l app=chaos-injector --tail=200
```

Check created Jobs:

```bash
kubectl -n cassandra-lab get jobs
kubectl -n cassandra-lab get pods -l app=nosqlbench -o wide
```

Check scenario config mounted:

```bash
kubectl -n cassandra-lab get configmap chaos-nosqlbench-scenarios -o yaml
```

Check histostat PVC/exporter:

```bash
kubectl -n cassandra-lab get pvc nosqlbench-histostats-pvc
kubectl -n cassandra-lab get configmap nosqlbench-histostats-exporter -o yaml
```

Check API quickly:

```bash
curl -sS http://localhost:8200/health
curl -sS http://localhost:8200/faults
```

## Developer Checklist

Before running tests:

1. `chaos-injector` pod is Running
2. `chaos-nosqlbench-scenarios` ConfigMap exists
3. RBAC objects are present
4. `PROMPUSH_URL` and histostat env vars are set as intended
5. required monitoring targets are up
6. start/stop APIs are reachable locally
7. artifacts are being written under `./artifacts/`

## Legacy Note

Cassandra-stress compatibility routes still exist in code.
For new work and documentation, use the NoSQLBench path described above.