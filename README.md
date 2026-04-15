# Cassandra UBL MVP (Distributed + Online Detection Demo)

This package contains an end-to-end MVP for online anomaly detection on Cassandra using paper-aligned UBL concepts.

## Strict Infrastructure Requirement

Final experiments must run on a true multi-host Kubernetes cluster (minimum 3 worker nodes).  
`docker-desktop` and `kind` are allowed for development only, not final result collection.

## Components

- `k8s/cassandra/`: distributed Cassandra StatefulSet (multi-node).
- `simulator/`: workload generator and control API.
- `ubl-learner/`: clean-room SOM + UBL learner service.
- `chaos-injector/`: Kubernetes-native fault injector API.
- `orchestrator/`: phase runner (`normal -> load -> chaos -> cooldown`).
- `reporting/`: report generation (`final_report.json` and `final_report.md`).
- `monitoring/`: Cassandra JMX + simulator PodMonitor for Prometheus.
- `docs/`: metric contract, protocol, runbook, and result templates.

## Quick Start

From `cassandra/`:

```bash
# macOS only: destructive 2Gi VM rebuild + k3s bootstrap
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

## Fault Profiles

- `memleak-like`
- `cpuhog-like`
- `network-congestion-like`
- `bottleneck-like`

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

The strict cluster guide includes macOS, Windows (PowerShell), and Linux setup paths, with `2Gi` VM memory recommendations.

## Notes

- The learner starts online scoring automatically after bootstrap training succeeds.
- Missing Tier A metrics invalidate a sample; values are never silently replaced with zero.
- Report terminology uses `network congestion` profile naming for paper/demo consistency.
