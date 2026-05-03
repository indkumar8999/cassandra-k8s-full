# Cassandra UBL Developer Repository

## Project Summary

This repository is the implementation project for **NCSU - CSC 724 - Advanced Distributed Systems**.  
It contains a full developer workflow for Cassandra anomaly detection with UBL, stress orchestration, monitoring, and reporting automation.

## Team Details

- **Aum Pandya** (`apandya4@ncsu.edu`) - stress setup, orchestration, mitigation, scenario workflow
- **Darsh Rank** (`drank@ncsu.edu`) - UBL learner, training/inference workflow
- **Dilip Kumar** (`nirala@ncsu.edu`) - cluster architecture, monitoring, infrastructure setup

## What Is In This Repository

- `k8s/`: Kubernetes manifests for namespace, Cassandra, learner, chaos injector, orchestrator
- `ubl-learner/`: online learner service
- `offline-training/`: offline sample collection, SOM training, kNN training, offline inference
- `chaos-injector/`: stress and fault control API
- `orchestrator/`: scenario runner scripts
- `monitoring/`: Prometheus, Grafana, PodMonitor, and metrics integration files
- `reporting/`: report generation scripts and report source files
- `scripts/`: deployment, validation, cleanup, and utility scripts
- `docs/`: focused component documentation

## Documentation Index

- Stress and chaos setup:
  - `docs/stress-setup.md`
- UBL learner and offline training setup:
  - `docs/ubl-setup.md`
- Architecture and platform setup:
  - `docs/architecture-setup.md`
- Mitigation and elastic replicas flow:
  - `docs/mitigation.md`
- Day-2 operations and troubleshooting:
  - `docs/operations-and-troubleshooting.md`

## End-to-End Setup and Run

Without this end-to-end setup, the project will not run correctly.
Use the sequence below from start to finish.

### Scope

- This section is a beginner-friendly runbook.
- It includes very basic terminal commands.
- Run outputs are stored in `./artifacts/` and `./offline-training/artifacts/`.

### Very Quick Summary

1. Open terminal and move to this folder.
2. Make sure tools are installed.
3. Make sure Kubernetes cluster is ready.
4. Build and push Docker images.
5. Deploy everything in strict order.
6. Start required port-forwards in separate terminals.
7. Run scenario scripts.
8. Check generated artifacts.

### Step 0 - Open terminal and verify folder

If you are new to terminal, run these commands:

```bash
pwd
ls
```

You should already be inside the `cassandra` folder.

### Step 1 - Check required tools

Run each command below.
If a command prints a version, that tool is installed.

```bash
docker --version
kubectl version --client
helm version
python3 --version
make --version
```

If Docker is not logged in, log in now:

```bash
docker login
```

### Step 2 - Prepare Kubernetes cluster

You need a Kubernetes cluster with:

- 1 control-plane node
- at least 2 worker nodes

#### Recommended path: VCL cluster

Use VCL for final runs.

Recommended VM sizing:

- 2 vCPU
- 4Gi RAM
- 50Gi disk

Node layout:

- Control-plane node: learner, chaos, monitoring services
- Worker nodes: Cassandra StatefulSet pods

#### 2.1 Reserve VCL machines

Reserve **4 Ubuntu Linux VMs** in VCL:

- `control-node` (control-plane)
- `worker-1`
- `worker-2`

Use the same SSH key on all machines.
Make sure you can SSH into all of them from your laptop.

#### 2.2 SSH to each VM and install base tools

Run this on each VM (`control-node`, `worker-1`, `worker-2`):

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates
```

#### 2.3 Install k3s on control-plane node

SSH into `control-node`, then run:

```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--write-kubeconfig-mode 644 --node-name control-node' sh -
sudo cat /var/lib/rancher/k3s/server/node-token
hostname
```

Copy the token value. You will use it on workers.

#### 2.4 Join worker nodes to cluster

For each worker (`worker-1`, `worker-2`), SSH and run:

```bash
curl -sfL https://get.k3s.io | K3S_URL='https://<CONTROL_NODE_IP>:6443' K3S_TOKEN='<TOKEN_FROM_CONTROL_NODE>' INSTALL_K3S_EXEC='--node-name <WORKER_NAME>' sh -
hostname
```

Replace:

- `<CONTROL_NODE_IP>` with control-plane VM IP
- `<TOKEN_FROM_CONTROL_NODE>` with token copied above
- `<WORKER_NAME>` with exact worker name (`worker-1`, `worker-2`)

#### 2.5 Copy kubeconfig to your local machine

On your laptop (not on VM), run:

```bash
mkdir -p "./artifacts"
ssh <YOUR_VCL_USER>@<CONTROL_NODE_IP> "sudo cat /etc/rancher/k3s/k3s.yaml" > "./artifacts/kubeconfig-vcl.yaml"
sed -i '' "s/127.0.0.1/<CONTROL_NODE_IP>/g" "./artifacts/kubeconfig-vcl.yaml"
export KUBECONFIG="./artifacts/kubeconfig-vcl.yaml"
```

Now verify cluster access:

```bash
kubectl get nodes -o wide
kubectl cluster-info
```

#### 2.6 Node naming check (important)

Some manifests expect specific hostnames.
Verify names:

```bash
kubectl get nodes -o wide
```

Expected names:

- `control-node` for control-plane service placement
- `worker-1`, `worker-2` in Cassandra node affinity

If your node names are different, update manifest affinity values under:

- `k8s/`
- `monitoring/`

#### 2.7 Basic cluster health checks

Run:

```bash
kubectl get ns
kubectl get nodes -o wide
kubectl get pods -A
```

If DNS/service discovery seems unstable:

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
kubectl -n cassandra-lab get endpoints
```

### Step 3 - Build and publish images

You are already in the `cassandra` folder:

```bash
pwd
```

Build images:

```bash
make build-images
```

Push images (replace values with your real Docker Hub user and tag):

```bash
make push-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
```

Update manifest image tags:

```bash
python3 ./scripts/set_dockerhub_images.py --user <your_user> --tag <your_tag> --root .
```

Show final image names:

```bash
make show-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
```

### Step 4 - Deploy stack in strict order

Run one command:

```bash
bash ./scripts/deploy_strict_order.sh
```

This script runs:

1. `make deploy-core`
2. Helm install/upgrade monitoring stack
3. `make deploy-monitoring`
4. `make deploy-mvp`
5. `make demo-preflight`

### Step 5 - Verify deployment

Run these checks:

```bash
kubectl get ns
kubectl -n cassandra-lab get pods -o wide
kubectl -n monitoring get pods
make demo-preflight
```

Preflight confirms:

- context is not `docker-desktop` or `kind`
- at least 3 Ready worker nodes
- `cassandra-lab` namespace exists
- Cassandra pods spread across distinct nodes
- Cassandra ring has at least 3 `UN` nodes

#### 5.1 Expected pod layout example (from control-node)

When deployment is healthy, `kubectl get po -A -o wide` should look similar to this:

```bash
NAMESPACE       NAME                                                     READY   STATUS      ...   NODE
cassandra-lab   cassandra-0                                              1/1     Running     ...   worker-1
cassandra-lab   cassandra-1                                              1/1     Running     ...   worker-2
cassandra-lab   cassandra-2                                              1/1     Running     ...   worker-1
cassandra-lab   cassandra-simulator-78969f8b8f-jlx5h                     1/1     Running     ...   control-node
cassandra-lab   chaos-injector-75978bf4d5-hqgrp                          1/1     Running     ...   control-node
cassandra-lab   ubl-learner-794f5db49b-jdrr4                             1/1     Running     ...   control-node
monitoring      kube-prom-stack-grafana-74444b85-t8j26                   3/3     Running     ...   control-node
monitoring      prometheus-kube-prom-stack-kube-prome-prometheus-0       2/2     Running     ...   control-node
monitoring      prometheus-pushgateway-57c985896b-s5bjs                  1/1     Running     ...   control-node
monitoring      victoria-metrics-nb-68f6fc6c57-txg2p                     1/1     Running     ...   control-node
```

Quick check command:

```bash
kubectl get po -A -o wide
```

### Step 6 - Start required port-forwards (separate terminals)

Open many terminal windows/tabs.
Run one command per terminal.
Keep each command running.

#### Terminal 1 (simulator)

```bash
while true; do kubectl port-forward --address 0.0.0.0 -n cassandra-lab svc/cassandra-simulator 8080:8080; sleep 1; done
```

#### Terminal 2 (learner)

```bash
while true; do kubectl port-forward --address 0.0.0.0 -n cassandra-lab svc/ubl-learner 8100:8100; sleep 1; done
```

#### Terminal 3 (chaos)

```bash
while true; do kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200; sleep 1; done
```

#### Terminal 4 (Grafana)

```bash
while true; do kubectl port-forward --address 0.0.0.0 -n monitoring svc/kube-prom-stack-grafana 3000:80; sleep 1; done
```

#### Terminal 5 (Prometheus)

```bash
while true; do kubectl port-forward --address 0.0.0.0 -n monitoring svc/kube-prom-stack-kube-prome-prometheus 9090:9090; sleep 1; done
```

#### Terminal 6 (Pushgateway)

```bash
kubectl -n monitoring port-forward svc/prometheus-pushgateway 9091:9091
```

#### Terminal 7 (command terminal for runs)

```bash
pwd
```

#### Terminal 8 (NoSQLBench job metrics pod-forward)

Set the Job name first:

```bash
export JOB="<job-name>"
```

Wait for the job pod to be Running:

```bash
while true; do
  POD=$(kubectl -n cassandra-lab get pods -l job-name="$JOB" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  PHASE=$(kubectl -n cassandra-lab get pod "$POD" -o jsonpath='{.status.phase}' 2>/dev/null)
  echo "POD=${POD:-<none>} phase=${PHASE:-<none>}"
  [ "$PHASE" = "Running" ] && break
  sleep 1
done
```

Then forward the pod metrics port:

```bash
kubectl -n cassandra-lab port-forward pod/"$POD" 9406:9406
```

### Step 7 - Confirm service health before run

In the command terminal:

```bash
curl -sS http://localhost:8080/health
curl -sS http://localhost:8100/health
curl -sS http://localhost:8200/health
```

You should get JSON health responses.

### Step 8 - Run end-to-end test cases 

Run these test cases exactly as shown.

#### TEST-CASE-1 BASELINE

```bash
python3 orchestrator/run_scenario_nosqlbench.py \
  --output-dir ./artifacts \
  --bootstrap-fault-profile baseline-normal \
  --fault-profile baseline-normal \
  --chaos-sec 0 \
  --cooldown-sec 30
```

#### TEST-CASE-2 SHORT CPU SPIKE

```bash
python3 orchestrator/run_scenario_nosqlbench.py \
  --output-dir ./artifacts \
  --fault-profile baseline-normal \
  --chaos-sec 1 \
  --start-fault-profile short-cpu-spike \
  --start-fault-duration-sec 10 \
  --start-fault-target-mode one \
  --start-fault-target-pod cassandra-0 \
  --cooldown-sec 30
```

#### TEST-CASE-3 CPU PRESSURE

```bash
python3 orchestrator/run_scenario_nosqlbench.py \
  --output-dir ./artifacts \
  --fault-profile anomaly-concurrency-spike \
  --load-profile high \
  --chaos-sec 60 \
  --nb-threads 64 \
  --nb-parallel-jobs 6 \
  --cooldown-sec 30
```

#### TEST-CASE-4 DISK PRESSURE

```bash
python3 orchestrator/run_scenario_nosqlbench.py \
  --output-dir ./artifacts \
  --fault-profile anomaly-memory-pressure \
  --load-profile high \
  --chaos-sec 30 \
  --nb-threads 48 \
  --nb-parallel-jobs 4 \
  --cooldown-sec 30
```

#### TEST-CASE-5 MEMORY PRESSURE

```bash
python3 orchestrator/run_scenario_nosqlbench.py \
  --output-dir ./artifacts \
  --fault-profile anomaly-compaction-pressure \
  --load-profile high \
  --chaos-sec 30 \
  --nb-threads 48 \
  --nb-parallel-jobs 4 \
  --cooldown-sec 30
```

### Step 9 - Check output artifacts

List artifacts:

```bash
ls -la ./artifacts
ls -la ./offline-training/artifacts
```

Common output files:

- `artifacts/<run-id>/final_report.json`
- `artifacts/<run-id>/final_report.md`
- `artifacts/ablation_report.json`
- `artifacts/ablation_report.md`

### Step 10 - Cleanup (when done)

```bash
make cleanup-mvp
```

## Legacy Code

- Cassandra stress path is legacy-compatible.
- Current stress scenario path is NoSQLBench-driven via `k8s/chaos-injector/chaos-nosqlbench-scenarios-configmap.yaml`.

## Artifacts and Output Locations

- Scenario outputs: `./artifacts/<run-id>/`
- Per-run report files: `final_report.json`, `final_report.md`
- Grouped report files: `./artifacts/ablation_report.json`, `./artifacts/ablation_report.md`
- Offline training artifacts: `./offline-training/artifacts/`

