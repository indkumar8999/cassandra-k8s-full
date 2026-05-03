# Operations and Troubleshooting

Author: Aum Pandya (apandya4@ncsu.edu), Darsh Rank (drank@ncsu.edu), Dilip Kumar (nirala@ncsu.edu)

This guide helps with day-2 operations.
It includes common failures and direct fixes.

## Daily Operations Checklist

Run these checks before each run:

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl -n cassandra-lab get pods -o wide
kubectl -n monitoring get pods
make demo-preflight
```

## Common Issues and Fixes

### 1) `namespace "cassandra-lab" not found`

Cause: core resources were not deployed first.

Fix:

```bash
make deploy-core
bash ./scripts/deploy_strict_order.sh
```

### 2) Not enough Ready workers

Cause: worker VM down or not ready.

Fix:

```bash
kubectl get nodes -o wide
```

Recover the worker VM, then rerun:

```bash
make demo-preflight
```

### 3) Cassandra pods not spread across nodes

Cause: rollout still in progress or node affinity mismatch.

Fix:

```bash
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
kubectl -n cassandra-lab get pods -l app=cassandra -o wide
```

If affinity names do not match real hostnames, update manifest affinity values.

### 4) Cassandra ring does not show 3 `UN`

Fix:

```bash
kubectl exec -n cassandra-lab cassandra-0 -- env -u JVM_OPTS nodetool status
```

Wait for readiness and rerun preflight:

```bash
make demo-preflight
```

### 5) Port-forward exits repeatedly

Use resilient loops in separate terminals:

```bash
while true; do kubectl port-forward -n cassandra-lab svc/ubl-learner 8100:8100; sleep 1; done
while true; do kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200; sleep 1; done
```

### 6) Health endpoint does not respond

Check services, endpoints, and pods:

```bash
kubectl -n cassandra-lab get svc
kubectl -n cassandra-lab get endpoints
kubectl -n cassandra-lab get pods -o wide
curl -sS http://localhost:8100/health
curl -sS http://localhost:8200/health
```

### 7) `ModuleNotFoundError: requests` for local scripts

Install orchestrator dependencies:

```bash
python3 -m pip install -r orchestrator/requirements.txt
```

Use a virtual environment if your system Python is externally managed.

### 8) `zsh` parse errors when pushing images

Cause: placeholder syntax was copied literally.

Wrong:

```bash
make push-images DOCKERHUB_USER=<user> IMAGE_TAG=<tag>
```

Correct:

```bash
make push-images DOCKERHUB_USER=aumpandya IMAGE_TAG=v0.3.0
```

## Operational Commands

Restart learner deployment:

```bash
kubectl -n cassandra-lab rollout restart deployment/ubl-learner
kubectl -n cassandra-lab rollout status deployment/ubl-learner --timeout=300s
```

Restart chaos injector:

```bash
kubectl -n cassandra-lab rollout restart deployment/chaos-injector
kubectl -n cassandra-lab rollout status deployment/chaos-injector --timeout=300s
```

Scale Cassandra manually:

```bash
kubectl -n cassandra-lab scale statefulset cassandra --replicas=4
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
```

## Artifact Hygiene

Artifacts can grow over time.
Use clear run IDs and clean old test runs when needed.

Common artifact paths:

- `cassandra/artifacts/`
- `cassandra/offline-training/artifacts/`

## Legacy Notes

- Cassandra stress path is legacy-compatible.
- Prefer NoSQLBench-based stress scenarios for current work.
