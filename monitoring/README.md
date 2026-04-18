# Cassandra Monitoring Setup

Includes:
- kube-prometheus-stack Helm values
- Cassandra JMX exporter config
- StatefulSet patch
- PodMonitor
- Simulator PodMonitor

## Apply monitoring pieces

```bash
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f cassandra/monitoring/kube-prometheus-stack-values.yaml

kubectl apply -f cassandra/monitoring/cassandra-jmx-configmap.yaml
kubectl patch statefulset cassandra -n cassandra-lab --patch-file cassandra/monitoring/cassandra-statefulset-patch.yaml
kubectl apply -f cassandra/monitoring/cassandra-podmonitor.yaml
kubectl apply -f cassandra/monitoring/simulator-podmonitor.yaml
kubectl apply -f cassandra/monitoring/ubl-learner-podmonitor.yaml
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
