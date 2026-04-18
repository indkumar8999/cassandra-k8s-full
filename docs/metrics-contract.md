# Metrics Contract for Cassandra UBL MVP

This document defines the fixed metric input contract used by the UBL learner.
The contract is split into two tiers:

- Tier A: mandatory paper-like core metrics (CPU, memory, disk I/O, network I/O).
- Tier B: system-specific Cassandra and simulator metrics for richer diagnosis.

The learner treats missing required metrics as invalid samples (never as `0`).

## Prometheus Scope

- Prometheus endpoint: kube-prometheus-stack service.
- Scrape interval target: `15s`.
- Query lookback window default: `1m`.

## Tier A: Mandatory UBL-Aligned Features (Per Cassandra Pod)

Tier A is now vectorized per pod to avoid fault dilution. For each pod in:

- `cassandra-0`
- `cassandra-1`
- `cassandra-2`

the learner creates one feature per Tier A metric, e.g.:

- `tier_a_cpu_usage_cores__cassandra-0`
- `tier_a_cpu_usage_cores__cassandra-1`
- `tier_a_cpu_usage_cores__cassandra-2`

Total Tier A dimension = `6 metrics * 3 pods = 18`.

### CPU usage

- `tier_a_cpu_usage_cores__<pod>`
- PromQL:
  - `sum(rate(container_cpu_usage_seconds_total{namespace="cassandra-lab",pod="<pod>"}[1m]))`
- Unit: cores
- Expected normal range: cluster-dependent
- Rationale: direct compute pressure signal.

### Memory usage/pressure

- `tier_a_memory_working_set_bytes__<pod>`
- PromQL:
  - `sum(container_memory_working_set_bytes{namespace="cassandra-lab",pod="<pod>"})`
- Unit: bytes
- Expected normal range: deployment-dependent
- Rationale: captures memleak-like behavior and pressure buildup.

### Disk I/O rate

- `tier_a_disk_read_bytes_per_sec__<pod>`
- PromQL:
  - `sum(rate(container_fs_reads_bytes_total{namespace="cassandra-lab",pod="<pod>"}[1m]))`
- Unit: bytes/s

- `tier_a_disk_write_bytes_per_sec__<pod>`
- PromQL:
  - `sum(rate(container_fs_writes_bytes_total{namespace="cassandra-lab",pod="<pod>"}[1m]))`
- Unit: bytes/s

- Rationale: proxies storage pressure and contention.

### Network I/O

- `tier_a_network_rx_bytes_per_sec__<pod>`
- PromQL:
  - `sum(rate(cassandra_metrics_count{namespace="cassandra-lab",pod="<pod>",type="ClientMessageSize",metric="BytesReceived"}[1m]))`
- Unit: bytes/s

- `tier_a_network_tx_bytes_per_sec__<pod>`
- PromQL:
  - `sum(rate(cassandra_metrics_count{namespace="cassandra-lab",pod="<pod>",type="ClientMessageSize",metric="BytesSent"}[1m]))`
- Unit: bytes/s

## Tier B: Cassandra/Simulator Extensions

### Simulator throughput and latency

- `tier_b_simulator_write_success_total`
  - `sum(simulator_writes_success_total{namespace="cassandra-lab"})`
- `tier_b_simulator_read_success_total`
  - `sum(simulator_reads_success_total{namespace="cassandra-lab"})`
- `tier_b_simulator_write_latency_p95_ms`
  - `max(simulator_write_latency_p95_ms{namespace="cassandra-lab"})`
- `tier_b_simulator_read_latency_p95_ms`
  - `max(simulator_read_latency_p95_ms{namespace="cassandra-lab"})`

### Cassandra/JVM internals (from JMX exporter)

- `tier_b_jvm_heap_used_bytes`
  - `sum(jvm_memory_heap_used_bytes{namespace="cassandra-lab"})`
- `tier_b_cassandra_client_request_count_per_sec`
  - `sum(rate(cassandra_metrics_count{namespace="cassandra-lab",type="ClientRequest"}[1m]))`

## Sample Quality Rules

- Required Tier A values must all be present and finite.
- A sample is dropped if any Tier A metric is missing, NaN, or Inf.
- Tier B metrics may be missing; if missing they are omitted from the vector, not replaced by `0`.
- Every scored sample stores `quality.valid=true/false` with `quality.missing_features`.

## Paper Alignment Mapping

- CPU -> `tier_a_cpu_usage_cores__<pod>`
- Memory -> `tier_a_memory_working_set_bytes__<pod>`
- Disk I/O -> `tier_a_disk_read_bytes_per_sec__<pod>`, `tier_a_disk_write_bytes_per_sec__<pod>`
- Network I/O -> `tier_a_network_rx_bytes_per_sec__<pod>`, `tier_a_network_tx_bytes_per_sec__<pod>`

## Fault-to-Feature Fidelity Matrix

This section states which learned signals are expected to move for each injected profile. Chaos profiles are defined in `chaos-injector/main.py` (includes `anomaly-*` cassandra-stress recipes and legacy aliases `cpuhog-like` / `memleak-like`).

- `anomaly-concurrency-spike` (cassandra-stress load; alias **`cpuhog-like`** reports the same family of stress)
  - Primary: per-node CPU for Cassandra pods under load
  - Secondary: per-node disk/network and simulator latency/throughput
- `anomaly-compaction-pressure` (cassandra-stress; alias **`memleak-like`**)
  - Primary: per-node memory / pressure and compaction-related signals
  - Secondary: per-node CPU/disk and JVM heap usage
- `anomaly-hot-partition`, `anomaly-ttl-tombstone`, `anomaly-mixed-skew-large-payload` (cassandra-stress variants)
  - Primary: skewed partitions, TTL/tombstone path, or large-payload mix — expect Tier A + Tier B shifts per workload
- `bottleneck-like` (scale StatefulSet replicas down)
  - Primary: per-node CPU/memory/disk/network shifts across surviving pods
  - Secondary: simulator p95 latencies and success totals
- `network-congestion-like` (egress restriction on simulator pod)
  - Primary: simulator throughput/latency Tier B metrics
  - Secondary: Cassandra client message bytes rates (Tier A network)
  - Note: this is client-path congestion, not low-level packet loss/tc emulation.

## Fault Profile EDA Metrics

For each injection run, track:

- Fault profile name/version
- Target selector (pod/node/path)
- Injection parameters
- Start/stop commanded timestamps
- Start/stop verified timestamps
- Recovery markers

These fields are persisted with run-level artifacts for comparability.
