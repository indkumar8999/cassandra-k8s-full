# Cassandra Monitoring Setup

Includes:
- kube-prometheus-stack Helm values
- Cassandra JMX exporter config
- StatefulSet patch
- PodMonitor
- Simulator PodMonitor

## Apply monitoring pieces

Helm values pin Grafana, Prometheus, Alertmanager, the Prometheus Operator, and kube-state-metrics to the node whose hostname is **`control-node`** (`kubernetes.io/hostname`). Adjust `kube-prometheus-stack-values.yaml` if your platform VM registers under a different name.

```bash
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f cassandra/monitoring/kube-prometheus-stack-values.yaml

# Includes `victoria-metrics-nb` (NoSQLBench push ingest). Grafana adds datasource `VictoriaMetrics-NB`
# for PromQL over those series (VM does not support Prometheus remote_read /api/v1/read).
# chaos-injector default `PROMPUSH_URL=victoria:plain:…` (expanded to `http://…/api/v1/import/prometheus/metrics/job/…` for NB).

kubectl apply -f cassandra/monitoring/cassandra-jmx-configmap.yaml
kubectl patch statefulset cassandra -n cassandra-lab --patch-file cassandra/monitoring/cassandra-statefulset-patch.yaml
kubectl apply -f cassandra/monitoring/cassandra-podmonitor.yaml
kubectl apply -f cassandra/monitoring/simulator-podmonitor.yaml
kubectl apply -f cassandra/monitoring/ubl-learner-podmonitor.yaml
kubectl apply -f cassandra/monitoring/chaos-injector-podmonitor.yaml
kubectl apply -f cassandra/monitoring/nosqlbench-histostats-podmonitor.yaml
```

The simulator is scraped from `GET /metrics/prometheus`.

## Grafana demo dashboard (scenarios)

This repo includes a provisioned Grafana dashboard for demoing **5–10 scenarios** (load profiles) using the simulator’s `simulator_profile_state{profile=...}` one-hot metric.

Apply it:

```bash
kubectl apply -f cassandra/monitoring/grafana-dashboard-cassandra-lab.yaml
```

Then open Grafana (NodePort **32000**) and look for:

- **Dashboard**: `Cassandra Lab Demo (Scenarios + Load Profiles)`
- **Dropdowns**: `Scenario` (multi-select) and `Pod` (multi-select)
