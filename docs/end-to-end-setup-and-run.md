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

Important:

- if learner is forwarded on `18100`, you must set `LEARNER_BASE=http://localhost:18100`
- if learner is forwarded on `8100`, unset `LEARNER_BASE` (default)

Examples:

```bash
# default mapping (recommended)
unset LEARNER_BASE
```

```bash
# alternate mapping (when 8100 is busy)
export LEARNER_BASE="http://localhost:18100"
while true; do kubectl port-forward -n cassandra-lab svc/ubl-learner 18100:8100; sleep 1; done
```

### Port-forward loop looks "stuck" with no logs

This is often normal: `kubectl port-forward` stays in foreground and can be quiet until traffic arrives.

Verify endpoint from another terminal:

```bash
curl -sS http://localhost:8080/health
curl -sS http://localhost:8100/health
curl -sS http://localhost:8200/health
```

If one service fails while others pass, inspect service endpoints:

```bash
kubectl -n cassandra-lab get svc
kubectl -n cassandra-lab get endpoints
kubectl -n cassandra-lab get pods -o wide
```

If `curl http://localhost:8100/health` fails but learner pod is Running:

```bash
kubectl -n cassandra-lab get endpoints ubl-learner -o yaml
```

- if endpoint appears under `notReadyAddresses`, service forwarding will fail
- recover node/pod readiness first, then retry port-forward

### Preflight says fewer than 3 Ready workers

A worker may have dropped to `NotReady` (common after VM hiccups). Recover worker VM first:

```bash
multipass list
multipass stop --force w1
multipass start w1
kubectl wait --for=condition=Ready node/w1 --timeout=180s
kubectl get nodes -o wide
```

Then rerun:

```bash
make demo-preflight
```

If a specific worker keeps flapping (`NotReady`), also restart agent service after VM start:

```bash
multipass exec w1 -- sudo systemctl restart k3s-agent
kubectl wait --for=condition=Ready node/w1 --timeout=240s
```

Then refresh learner pod placement if needed:

```bash
kubectl -n cassandra-lab rollout restart deployment/ubl-learner
kubectl -n cassandra-lab rollout status deployment/ubl-learner --timeout=300s
```

### `net/http: TLS handshake timeout` from kubectl/helm

This is usually transient API-server reachability or node instability.

Retry after confirming cluster health:

```bash
kubectl get nodes -o wide
kubectl -n cassandra-lab get pods -o wide
```

If a worker is `NotReady`, recover it first using the worker recovery steps above.

### `ModuleNotFoundError: No module named 'requests'` in orchestrator

The local Python venv is missing dependencies for local run scripts.

```bash
python3 -m pip install -r orchestrator/requirements.txt
```

Minimum quick fix:

```bash
python3 -m pip install requests
```

### `error: externally-managed-environment` when using `pip` (macOS/Homebrew Python)

You are using system Python. Install dependencies in the project virtualenv instead:

```bash
cd /Users/aumpandya/Documents/Projects/ads_project/cassandra
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r orchestrator/requirements.txt
```

Do not install with system pip unless you intentionally use `--break-system-packages`.

### `No such file or directory` for `orchestrator/requirements.txt` or `./scripts/run_ubl_tuning_batch.sh`

This is usually a current-directory issue.

From repo root, paths are:

```bash
python3 -m pip install -r cassandra/orchestrator/requirements.txt
bash cassandra/scripts/run_ubl_tuning_batch.sh
```

From `cassandra/`, paths are:

```bash
python3 -m pip install -r orchestrator/requirements.txt
bash ./scripts/run_ubl_tuning_batch.sh
```

### Command accidentally concatenated in shell

If a command like `...restart k3s-agentexport KUBECONFIG=...` appears, shell parsed two commands as one line.
Always run one command per line.

## 10) Recommended shell persistence

To avoid stale context in new terminals, add to `~/.zshrc`:

```bash
export KUBECONFIG="/Users/aumpandya/Documents/Projects/ads_project/cassandra/artifacts/kubeconfig-multipass-k3s.yaml"
```

For PowerShell persistence (new terminals):

```powershell
[Environment]::SetEnvironmentVariable("KUBECONFIG", "C:\Users\<you>\Documents\Projects\ads_project\cassandra\artifacts\kubeconfig-multipass-k3s.yaml", "User")
```

