# Cassandra UBL MVP (Distributed + Online Detection Demo)

This package contains an end-to-end MVP for online anomaly detection on Cassandra using paper-aligned UBL concepts.

## Strict Infrastructure Requirement

Final experiments must run on a true multi-host Kubernetes cluster (minimum 3 worker nodes).  
`docker-desktop` and `kind` are allowed for development only, not final result collection.

### Cassandra `Pending`: node affinity vs PVC volume affinity

The StatefulSet pins pods to **`aum-w1`**, **`dilip-w2`**, **`msi`**, and **`backup-w4`** (not `cp1`). If a pod (often **`cassandra-1`**) stays **`Pending`** with:

`didn't match Pod's node affinity` **and** `didn't match PersistentVolume's node affinity`,

the **PVC was usually created earlier** while the pod could still land on **`cp1`**, so the volume is **topology-bound** there while the pod may no longer schedule there. **No node** then satisfies both rules.

**Lab recovery (destroys that replica’s local data on its old volume):**

```bash
kubectl -n cassandra-lab delete pod cassandra-1 --wait=false
kubectl -n cassandra-lab delete pvc cassandra-data-cassandra-1
# StatefulSet recreates the pod; a new PVC binds on a worker that matches the Cassandra node hostname list.
kubectl -n cassandra-lab get pods -l app=cassandra -w
```

Confirm where the old volume lived: `kubectl -n cassandra-lab describe pvc cassandra-data-cassandra-1` (before delete) and check **Events** / **Volume** node affinity.

## Components

- `k8s/cassandra/`: distributed Cassandra StatefulSet (multi-node).
- `simulator/`: workload generator and control API.
- `ubl-learner/`: clean-room SOM + UBL learner service.
- `chaos-injector/`: Kubernetes-native fault injector API.
- `orchestrator/`: phase runner (`normal -> load -> chaos -> cooldown`; see `docs/experiment-protocol.md` for the full **A–F** demo story: mitigation **D**, Grafana/SLO **E**, elastic scale **D+F** via [`scripts/cassandra_elastic_replicas.sh`](scripts/cassandra_elastic_replicas.sh)).
- `reporting/`: report generation (`final_report.json` and `final_report.md`).
- `monitoring/`: Cassandra JMX + simulator PodMonitor for Prometheus.
- `docs/`: metric contract, protocol, runbook, and result templates.

## Quick Start

From `cassandra/`:

```bash
# macOS only: destructive Multipass rebuild + k3s bootstrap (4Gi RAM/VM default; 2Gi pressure: make rebuild-multipass-pressure)
# make rebuild-multipass-2g
# export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"

make build-images
make push-images DOCKERHUB_USER=<user> IMAGE_TAG=<tag>
python3 ./scripts/set_dockerhub_images.py --user <user> --tag <tag> --root .
bash ./scripts/deploy_strict_order.sh
make demo-preflight
```

Run a strict validation scenario:

```bash
bash ./scripts/run_strict_validation.sh bottleneck-like high
```

The validation script enforces a chaos sample quality gate in report generation (fails when chaos scored samples are too low).

Generate or refresh the latest report:

```bash
bash ./scripts/collect_latest_report.sh
```

**Mitigation cycle (scale out + scale in):** after port-forwards (see `docs/end-to-end-setup-and-run.md` §6), run [`scripts/cassandra_elastic_replicas.sh`](scripts/cassandra_elastic_replicas.sh) in its own terminal **before** chaos begins (or use `SCALE_OUT_MODE=prom_bad`). It waits for **CONSECUTIVE_CHAOS_ALARMS** (default **3**) consecutive `phase=="chaos"` alarms in time order after each cycle’s watch start (`CONSECUTIVE_CHAOS_ALARMS=1` restores the old single-alarm trigger), then scales **3→4**, waits for Prometheus SLO “OK”, and scales **4→3**. Set `ELASTIC_DAEMON=1` to repeat cycles; `PROMQL` / `SLO_THRESHOLD` for real scale-in gating.

```bash
export PROMETHEUS_BASE=http://localhost:9090
export PROMQL='vector(0)'
export SLO_THRESHOLD=1
bash ./scripts/cassandra_elastic_replicas.sh
```

Cleanup:

```bash
make cleanup-mvp
```

## APIs

### Simulator (`:8080`)

- `GET /health`
- `POST /load`
- `POST /pause`
- `POST /resume`
- `POST /reset-metrics`
- `GET /metrics` (JSON)
- `GET /metrics/prometheus` (Prometheus text)

### UBL Learner (`:8100`)

- `GET /health`
- `GET /status`
- `POST /phase`
- `GET /score-stream`
- `GET /alarms`
- `GET /report`
- `POST /reset`

### Chaos Injector (`:8200`)

- `GET /health`
- `GET /faults`
- `POST /start_fault`
- `POST /stop_fault`
- `POST /reset_all`

## Fault Profiles (chaos-injector)

Names are whatever `POST /start_fault` accepts (see `chaos-injector/main.py`). Primary recipes:

- `baseline-normal` (bootstrap / cassandra-stress)
- `anomaly-hot-partition`
- `anomaly-compaction-pressure`
- `anomaly-concurrency-spike`
- `anomaly-ttl-tombstone`
- `anomaly-mixed-skew-large-payload`
- `anomaly-university-memory-pressure` (cassandra-stress **user** profile; requires ConfigMap `chaos-university-stress-profile` — applied by `make deploy-mvp` from `chaos-injector/university-profile.yaml`)
- `network-congestion-like`
- `bottleneck-like`

Compatibility aliases (same implementation as an anomaly recipe, different reported profile): `cpuhog-like`, `memleak-like`.

With local port-forwards up, pass the profile to the orchestrator, for example:

`python3 orchestrator/run_scenario.py --output-dir ./artifacts --fault-profile anomaly-hot-partition --load-profile high`

## Metrics Model

The learner uses two feature tiers:

- Tier A (mandatory paper-like): CPU, memory, disk I/O, network I/O
- Tier B (optional extension): Cassandra and simulator internals

Full details and PromQL queries: `docs/metrics-contract.md`.

## Experiment and Demo Docs

- End-to-end setup/runbook: `docs/end-to-end-setup-and-run.md`
- Strict cluster guide: `docs/strict-zero-cost-cluster.md`
- Protocol: `docs/experiment-protocol.md`
- Results template: `docs/results-template.md`
- Presenter runbook: `docs/demo-runbook.md`

The strict cluster guide includes macOS, Windows (PowerShell), and Linux setup paths, with **`4Gi` per VM** as the default Multipass sizing for this stack.

## Notes

- The learner starts online scoring automatically after bootstrap training succeeds.
- Missing Tier A metrics invalidate a sample; values are never silently replaced with zero.
- Report terminology uses `network congestion` profile naming for paper/demo consistency.
