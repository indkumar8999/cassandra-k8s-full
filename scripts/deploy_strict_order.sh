#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[deploy] core"
make deploy-core

echo "[deploy] monitoring stack (helm)"
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update
helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f "${ROOT_DIR}/monitoring/kube-prometheus-stack-values.yaml"

echo "[deploy] monitoring podmonitors"
make deploy-monitoring

echo "[deploy] mvp services"
make deploy-mvp

echo "[deploy] strict preflight"
make demo-preflight

echo "[deploy] completed"
