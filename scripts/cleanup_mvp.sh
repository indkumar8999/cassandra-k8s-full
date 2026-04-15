#!/usr/bin/env bash
set -euo pipefail

echo "[cleanup] stopping orchestrator jobs"
kubectl delete job -n cassandra-lab scenario-orchestrator --ignore-not-found

echo "[cleanup] deleting learner and chaos services"
kubectl delete -f k8s/ubl-learner/ --ignore-not-found
kubectl delete -f k8s/chaos-injector/ --ignore-not-found
kubectl delete -f k8s/orchestrator/orchestrator-config.yaml --ignore-not-found

echo "[cleanup] resetting chaos injector active faults (best effort)"
if kubectl get svc -n cassandra-lab chaos-injector >/dev/null 2>&1; then
  kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200 >/tmp/chaos-pf.log 2>&1 &
  PF_PID=$!
  sleep 2
  curl -sS -X POST http://localhost:8200/reset_all || true
  kill ${PF_PID} >/dev/null 2>&1 || true
fi

echo "[cleanup] done"
