#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[deploy] applying core manifests"
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/cassandra/
kubectl apply -f k8s/simulator/

echo "[deploy] applying monitoring integration"
kubectl apply -f monitoring/cassandra-jmx-configmap.yaml
kubectl patch statefulset cassandra -n cassandra-lab --patch-file monitoring/cassandra-statefulset-patch.yaml
kubectl apply -f monitoring/cassandra-podmonitor.yaml
kubectl apply -f monitoring/simulator-podmonitor.yaml

echo "[deploy] applying learner + chaos + orchestrator config"
kubectl apply -f k8s/ubl-learner/
kubectl apply -f k8s/chaos-injector/
kubectl apply -f k8s/orchestrator/orchestrator-config.yaml

echo "[deploy] complete"
