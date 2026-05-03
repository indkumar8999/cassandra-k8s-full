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
5. optionally drive **local** `orchestrator/run_scenario.py` with port-forwards, use **Grafana** (phase E), and **elastic replicas** (phases D+F) via [`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) (see §6–7)

## 1) Prerequisites

- Repository checked out locally.
- Docker installed and logged in to Docker Hub.
- `kubectl`, `helm`, `python3`, and `make` installed.
- For macOS local cluster path: Multipass installed.

## 2) Cluster bootstrap

### Option A (macOS, recommended): destructive Multipass rebuild (4Gi RAM per VM by default)

From `cassandra/`:

```bash
make rebuild-multipass-2g
export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

Expected:

- 4 nodes ready (`cp1`, `w1`, `w2`, `w3`)
- server endpoint points to `192.168.2.x:6443` for current control-plane

### Option A‑pressure (macOS): smaller VMs (destructive)

Use when you want **higher fractional CPU/memory use** for the same stress (UBL / Grafana look “busier” on 2 vCPU boxes). Same rebuild script as Option A but **2G RAM per VM** (higher OOM risk under monitoring + heavy `cassandra-stress`):

```bash
make rebuild-multipass-pressure
export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

Equivalent without the Make target: `VM_MEMORY=2G make rebuild-multipass-2g` (the underlying script reads `VM_MEMORY`).

### Cassandra requests / limits (repo default, visible utilization)

The lab [`k8s/cassandra/cassandra-statefulset.yaml`](../k8s/cassandra/cassandra-statefulset.yaml) uses **raised** `resources.requests` (`900m` CPU, `1536Mi` memory) so idle + loaded Tier‑A metrics are more noticeable on **2 vCPU / ~4GiB** Multipass workers than the legacy `500m` / `1Gi` profile. After changing the manifest or refreshing an older cluster:

```bash
kubectl apply -f k8s/cassandra/cassandra-statefulset.yaml
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
```

### Option B (Windows PowerShell / Linux)

Use `docs/strict-zero-cost-cluster.md` platform sections and ensure:

- one control-plane + at least three workers
- each host at 2 vCPU / 4Gi / 20Gi minimum for Cassandra + monitoring on workers (use `VM_MEMORY=2G` only if your host is tight)
- `kubectl get nodes -o wide` shows all Ready

### Option C (Windows PowerShell, explicit commands)

From PowerShell in the `cassandra` directory:

```powershell
winget install Canonical.Multipass

multipass launch 22.04 --name cp1 --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w1  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w2  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w3  --cpus 2 --memory 4G --disk 20G

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

Run these in **separate terminals** (resilient loops):

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

### Fourth terminal: Grafana (mitigation / SLO narrative)

Use either NodePort (often simplest on Multipass: worker IP and port **32000**, admin password in `monitoring/kube-prometheus-stack-values.yaml`) or a forward to the Grafana service created by Helm (release name `kube-prom-stack`):

```bash
while true; do kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80; sleep 1; done
```

Then open `http://localhost:3000` (login `admin` / `admin123` unless you changed values). Apply the lab dashboard if needed: `kubectl apply -f monitoring/grafana-dashboard-cassandra-lab.yaml` (from repo paths as in `monitoring/README.md`).

### Prometheus API (elastic replicas + SLO scale-in, phases D/F)

[`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) calls `GET ${PROMETHEUS_BASE}/api/v1/query` for the scale-**in** leg. Port-forward the **Prometheus server** Service in `monitoring`. With Helm release `kube-prom-stack`, Kubernetes often **truncates** the Service name. Discover yours:

```bash
kubectl -n monitoring get svc | rg -i 'prometheus'
```

Typical server Service (NodePort **9090** in the `PORT(S)` column):

```bash
while true; do kubectl port-forward -n monitoring svc/kube-prom-stack-kube-prome-prometheus 9090:9090; sleep 1; done
```

If your `kubectl get svc` shows a different Prometheus server name, substitute it in the command above. Then set `PROMETHEUS_BASE=http://localhost:9090`. Alternatively use NodePort **32090** on a worker IP (see `monitoring/kube-prometheus-stack-values.yaml`) if your network path can reach it.

### Optional fifth terminal: tail learner alarms

```bash
while true; do date; curl -sS "http://localhost:8100/alarms?limit=20"; echo; sleep 1; done
```

Responses are a bounded recent list; timestamps can span bootstrap, chaos, cooldown, and any later scoring if you keep polling after the scenario script finishes.

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

- batch chaos defaults assume workers have enough RAM (4Gi+ per Multipass VM is the supported default)
- report generation includes quality gate checks
- runs fail fast when chaos scoring coverage is too low

### Local `run_scenario.py` (same ports as §6)

With the three `cassandra-lab` port-forwards on **8080 / 8100 / 8200**, from the `cassandra/` directory:

```bash
python3 orchestrator/run_scenario.py --output-dir ./artifacts
```

Use `python3 orchestrator/run_scenario.py --help` for fault profile, chaos duration, bootstrap options, and bases (`SIMULATOR_BASE`, `LEARNER_BASE`, `CHAOS_BASE` env vars override defaults).

This script implements **phases A–C** plus orchestrator **cooldown**; it does **not** scale the cluster by itself.

### Phases D + F: one script — elastic Cassandra replicas

Use Grafana (**phase E**) for panels during/after stress. For **scale out then scale in** in one process, run [`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) in **another terminal** while port-forwards for **8100** (learner) and **9090** (Prometheus) are up (and start it **before** or **as** chaos begins so the “new chaos alarm” window is meaningful).

Default scale-out signal is a **new** alarm with `phase == "chaos"` recorded **after the script starts** (avoids the old bug where any non-empty `/alarms` buffer scaled out on stale history). Optional: `SCALE_OUT_MODE=prom_bad` or `both` — see the script header.

```bash
export LEARNER_BASE=http://localhost:8100
export PROMETHEUS_BASE=http://localhost:9090
export PROMQL='vector(0)'
export SLO_THRESHOLD=1
export SLO_COMPARISON=lt
export STABLE_OK_SEC=15
bash ./scripts/cassandra_elastic_replicas.sh
```

Manual scale-out only (no automation), then run the same script with replicas already at **4** to perform **scale-in only** (it skips the scale-out wait):

```bash
kubectl -n cassandra-lab scale statefulset cassandra --replicas=4
kubectl -n cassandra-lab rollout status statefulset/cassandra --timeout=900s
# then same cassandra_elastic_replicas.sh as above for SLO-gated scale-in
```

- **`SLO_COMPARISON`:** `lt` / `lte` = OK when the sample is below threshold (typical for latency); `gt` / `gte` for minimum-throughput style checks.
- **Demo vs production:** **demo-grade**. Production shrink normally requires **decommission** before lowering replica count.

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

