# Cassandra UBL End-to-End Setup and Run

This guide is the fastest path to go from a fresh machine to a full strict run.

It is designed for:

- first-time setup
- rebuilt clusters
- troubleshooting common bootstrap and port-forward failures

## 0) What this runbook guarantees

By following this document, you will:

1. provision or rebuild a strict multi-node Kubernetes cluster
2. deploy Cassandra + simulator + learner + chaos + monitoring in the correct order
3. validate strict placement and ring health
4. run tuning experiments with quality gates enabled

## 1) Prerequisites

- Repository checked out locally.
- Docker installed and logged in to Docker Hub.
- `kubectl`, `helm`, `python3`, and `make` installed.
- For macOS local cluster path: Multipass installed.

## 2) Cluster bootstrap

### Option A (macOS, recommended): destructive 2Gi rebuild

From `cassandra/`:

```bash
make rebuild-multipass-2g
export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

Expected:

- 4 nodes ready (`cp1`, `w1`, `w2`, `w3`)
- server endpoint points to `192.168.2.x:6443` for current control-plane

### Option B (Windows PowerShell / Linux)

Use `docs/strict-zero-cost-cluster.md` platform sections and ensure:

- one control-plane + at least three workers
- each host at 2 vCPU / 2Gi / 20Gi minimum
- `kubectl get nodes -o wide` shows all Ready

### Option C (Windows PowerShell, explicit commands)

From PowerShell in the `cassandra` directory:

```powershell
winget install Canonical.Multipass

multipass launch 22.04 --name cp1 --cpus 2 --memory 2G --disk 20G
multipass launch 22.04 --name w1  --cpus 2 --memory 2G --disk 20G
multipass launch 22.04 --name w2  --cpus 2 --memory 2G --disk 20G
multipass launch 22.04 --name w3  --cpus 2 --memory 2G --disk 20G

multipass exec cp1 -- bash -lc "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--write-kubeconfig-mode 644 --node-name cp1' sh -"
$token = multipass exec cp1 -- sudo cat /var/lib/rancher/k3s/server/node-token
$cpIp = (multipass info cp1 | Select-String "IPv4").ToString().Split()[-1]

multipass exec w1 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w1' sh -"
multipass exec w2 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w2' sh -"
multipass exec w3 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w3' sh -"

New-Item -ItemType Directory -Force -Path .\artifacts | Out-Null
multipass exec cp1 -- sudo cat /etc/rancher/k3s/k3s.yaml | Out-File -Encoding ascii .\artifacts\kubeconfig-multipass-k3s.yaml
(Get-Content .\artifacts\kubeconfig-multipass-k3s.yaml) -replace "127.0.0.1", $cpIp | Set-Content .\artifacts\kubeconfig-multipass-k3s.yaml
$env:KUBECONFIG = (Resolve-Path .\artifacts\kubeconfig-multipass-k3s.yaml)
kubectl get nodes -o wide
```

## 3) Build and publish images

Use real values (no angle brackets):

```bash
make build-images
make push-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
python3 ./scripts/set_dockerhub_images.py --user <your_user> --tag <your_tag> --root .
make show-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
```

PowerShell equivalent:

```powershell
make build-images
make push-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
python .\scripts\set_dockerhub_images.py --user <your_user> --tag <your_tag> --root .
make show-images DOCKERHUB_USER=<your_user> IMAGE_TAG=<your_tag>
```

## 4) Deploy in strict order

Always deploy core first, then monitoring, then MVP:

```bash
bash ./scripts/deploy_strict_order.sh
```

PowerShell equivalent:

```powershell
bash .\scripts\deploy_strict_order.sh
```

If preflight fails early because Cassandra is still rolling out, wait and rerun:

```bash
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
make demo-preflight
```

## 5) Mandatory verification checks

```bash
kubectl get ns
kubectl -n cassandra-lab get pods -l app=cassandra -o wide
kubectl -n cassandra-lab get pods -o wide
make demo-preflight
```

Expected:

- `cassandra-0/1/2` all Ready
- each Cassandra pod on a distinct worker node
- ring health shows 3 `UN` nodes

## 6) Reliable local port-forwards (required for local orchestrator scripts)

Run these in three separate terminals:

```bash
while true; do kubectl port-forward -n cassandra-lab svc/cassandra-simulator 8080:8080; sleep 1; done
```

```bash
while true; do kubectl port-forward -n cassandra-lab svc/ubl-learner 8100:8100; sleep 1; done
```

```bash
while true; do kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200; sleep 1; done
```

PowerShell equivalent (three separate terminals):

```powershell
while ($true) { kubectl port-forward -n cassandra-lab svc/cassandra-simulator 8080:8080; Start-Sleep -Seconds 1 }
```

```powershell
while ($true) { kubectl port-forward -n cassandra-lab svc/ubl-learner 8100:8100; Start-Sleep -Seconds 1 }
```

```powershell
while ($true) { kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200; Start-Sleep -Seconds 1 }
```

## 7) Run experiment workflows

### Single strict validation run

```bash
bash ./scripts/run_strict_validation.sh bottleneck-like high
```

PowerShell equivalent:

```powershell
bash .\scripts\run_strict_validation.sh bottleneck-like high
```

### Intensity-focused A/B/C tuning batch

```bash
bash ./scripts/run_ubl_tuning_batch.sh
```

PowerShell equivalent:

```powershell
bash .\scripts\run_ubl_tuning_batch.sh
```

Notes:

- batch now uses stronger chaos defaults suitable for 2Gi nodes
- report generation includes quality gate checks
- runs fail fast when chaos scoring coverage is too low

## 8) Analyze outputs

Per-run output:

- `artifacts/<run-id>/final_report.json`
- `artifacts/<run-id>/final_report.md`

Grouped output:

- `artifacts/ablation_report.json`
- `artifacts/ablation_report.md`

Reports now include:

- scored samples by phase
- dropped sample counters (Tier A / Tier B)
- run quality gate result
- acceptance criteria result

## 9) Common failures and exact fixes

### `namespace "cassandra-lab" not found`

You deployed MVP before core:

```bash
make deploy-core
bash ./scripts/deploy_strict_order.sh
```

### `Unable to connect ... 192.168.2.2:6443 host is down`

Your `kubectl` endpoint is stale after rebuild. Reset kubeconfig:

```bash
export KUBECONFIG="/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

PowerShell:

```powershell
$env:KUBECONFIG = (Resolve-Path .\artifacts\kubeconfig-multipass-k3s.yaml)
kubectl get nodes -o wide
```

### Preflight says Cassandra pods not distributed across 3 nodes

Usually rollout timing. Wait for StatefulSet completion:

```bash
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
make demo-preflight
```

### zsh parse error when running push command

Do not use placeholder brackets in commands.

Wrong:

```bash
make push-images DOCKERHUB_USER=<user> IMAGE_TAG=<tag>
```

Correct:

```bash
make push-images DOCKERHUB_USER=aumpandya IMAGE_TAG=v0.2.0
```

### Port-forward dies during rollouts

Use the `while true` loops shown above so they auto-recover.

## 10) Recommended shell persistence

To avoid stale context in new terminals, add to `~/.zshrc`:

```bash
export KUBECONFIG="/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/kubeconfig-multipass-k3s.yaml"
```

For PowerShell persistence (new terminals):

```powershell
[Environment]::SetEnvironmentVariable("KUBECONFIG", "C:\Users\<you>\Documents\Projects\ads_project\cassandra\artifacts\kubeconfig-multipass-k3s.yaml", "User")
```

