# Strict Zero-Cost Distributed Cluster Guide

This guide defines the mandatory infrastructure for final experiments.

For full build/deploy/run commands and troubleshooting, use `docs/end-to-end-setup-and-run.md`.

## Non-Negotiable Rule

- Final runs must not use `docker-desktop` or `kind`.
- Final runs must use at least 3 separate Linux VMs/hosts in one Kubernetes cluster.

## Recommended Topology

- 1 control-plane VM
- 3 worker VMs
- Recommended memory: **`4Gi` per Ubuntu VM** (control-plane and workers) when running Cassandra + kube-prometheus on workers; **`2Gi` per VM** is supported as a **pressure / demo** profile (see `make rebuild-multipass-pressure` in `cassandra/Makefile`) but OOMs under load are more likely—raise stress gradually.
- Ubuntu 22.04+ on all nodes
- Container runtime: `containerd`
- Kubernetes: `kubeadm` + CNI (Calico/Cilium)

This gives four total hosts (`cp1`, `w1`, `w2`, `w3`) while keeping local resource use manageable.

## Platform Paths

### macOS path (fastest)

Use Multipass to create Ubuntu VMs:

```bash
brew install --cask multipass
multipass launch 22.04 --name cp1 --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w1  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w2  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w3  --cpus 2 --memory 4G --disk 20G
```

Then bootstrap Kubernetes (k3s or kubeadm) inside those VMs.

Fully automated macOS rebuild (destructive, recommended):

```bash
cd cassandra
make rebuild-multipass-2g
export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

This script:

- deletes and recreates `cp1`, `w1`, `w2`, `w3`
- uses **`4G` RAM per Ubuntu VM** by default (`VM_MEMORY=2G` to override)
- installs k3s and joins all worker nodes
- writes kubeconfig to `artifacts/kubeconfig-multipass-k3s.yaml`

### Windows path (PowerShell)

Use PowerShell with Hyper-V + Multipass:

```powershell
winget install Canonical.Multipass

multipass launch 22.04 --name cp1 --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w1  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w2  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w3  --cpus 2 --memory 4G --disk 20G
```

Bootstrap k3s from PowerShell:

```powershell
# control-plane
multipass exec cp1 -- bash -lc "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--write-kubeconfig-mode 644 --node-name cp1' sh -"
$token = multipass exec cp1 -- sudo cat /var/lib/rancher/k3s/server/node-token
$cpIp = (multipass info cp1 | Select-String "IPv4").ToString().Split()[-1]

# workers
multipass exec w1 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w1' sh -"
multipass exec w2 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w2' sh -"
multipass exec w3 -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://$cpIp`:6443' K3S_TOKEN='$token' INSTALL_K3S_EXEC='--node-name w3' sh -"
```

The requirement is the same: one control-plane + at least three worker hosts.

Suggested minimum sizing for each Ubuntu host:

- vCPU: 2
- RAM: 4Gi (recommended for this stack)
- Disk: 20Gi

Export kubeconfig locally (PowerShell):

```powershell
New-Item -ItemType Directory -Force -Path .\artifacts | Out-Null
multipass exec cp1 -- sudo cat /etc/rancher/k3s/k3s.yaml | Out-File -Encoding ascii .\artifacts\kubeconfig-multipass-k3s.yaml
(Get-Content .\artifacts\kubeconfig-multipass-k3s.yaml) -replace "127.0.0.1", $cpIp | Set-Content .\artifacts\kubeconfig-multipass-k3s.yaml
$env:KUBECONFIG = (Resolve-Path .\artifacts\kubeconfig-multipass-k3s.yaml)
kubectl get nodes -o wide
```

### Linux path (bash)

Use either:

- Multipass
- KVM/libvirt
- Proxmox
- 4 physical machines on LAN

Ubuntu host creation example with Multipass:

```bash
multipass launch 22.04 --name cp1 --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w1  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w2  --cpus 2 --memory 4G --disk 20G
multipass launch 22.04 --name w3  --cpus 2 --memory 4G --disk 20G
```

Bootstrap k3s from Linux:

```bash
multipass exec cp1 -- bash -lc "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--write-kubeconfig-mode 644 --node-name cp1' sh -"
TOKEN="$(multipass exec cp1 -- sudo cat /var/lib/rancher/k3s/server/node-token)"
CP_IP="$(multipass info cp1 | awk '/IPv4/{print $2; exit}')"

for W in w1 w2 w3; do
  multipass exec "${W}" -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://${CP_IP}:6443' K3S_TOKEN='${TOKEN}' INSTALL_K3S_EXEC='--node-name ${W}' sh -"
done

mkdir -p ./artifacts
multipass exec cp1 -- sudo cat /etc/rancher/k3s/k3s.yaml > ./artifacts/kubeconfig-multipass-k3s.yaml
sed -i "s/127.0.0.1/${CP_IP}/g" ./artifacts/kubeconfig-multipass-k3s.yaml
export KUBECONFIG="$(pwd)/artifacts/kubeconfig-multipass-k3s.yaml"
kubectl get nodes -o wide
```

## Baseline Bootstrap (kubeadm)

On all nodes:

1. Install container runtime and kube tools (`kubeadm`, `kubelet`, `kubectl`).
2. Disable swap and ensure required kernel modules/sysctl settings are applied.

On control-plane:

1. `kubeadm init --pod-network-cidr=<CIDR>`
2. Configure `kubectl` for admin user.
3. Install CNI plugin.

On workers:

1. Join cluster with `kubeadm join ...`.

## Fast Bootstrap Alternative (k3s)

k3s is usually faster to stand up than kubeadm:

1. Install k3s server on `cp1`.
2. Join `w1`, `w2`, `w3` as agents with `K3S_URL` + token.
3. Merge kubeconfig into your local `kubectl` config and switch context.

Reference commands (manual):

Control-plane:

```bash
curl -sfL https://get.k3s.io | sh -
sudo cat /var/lib/rancher/k3s/server/node-token
```

Workers:

```bash
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<control-plane-ip>:6443 \
  K3S_TOKEN=<token-from-control-plane> sh -
```

## Strict Validation Gates

All gates below must pass before any experiment:

1. At least 3 Ready worker nodes.
2. Cassandra pods (`cassandra-0/1/2`) on distinct node names.
3. Cassandra ring health reports 3 `UN` nodes.
4. Learner bootstrap shows valid sample accumulation.

Use:

```bash
make demo-preflight
```

If this fails, do not run experiments.

## Image Policy

Use Docker Hub images with immutable tags:

- `docker.io/<user>/cassandra-simulator:<tag>`
- `docker.io/<user>/cassandra-ubl-learner:<tag>`
- `docker.io/<user>/cassandra-chaos-injector:<tag>`
- `docker.io/<user>/cassandra-orchestrator:<tag>`

Build/push using:

```bash
make build-images
make push-images DOCKERHUB_USER=<user> IMAGE_TAG=<tag>
python3 ./scripts/set_dockerhub_images.py --user <user> --tag <tag> --root .
```

## Deployment Order

1. `make deploy-core`
2. `make deploy-monitoring`
3. `make deploy-mvp`
4. `make demo-preflight`

Then run scenarios only after all checks pass.

## End-to-End From Scratch

After the cluster exists and `kubectl` points to it:

```bash
cd cassandra
make build-images
make push-images DOCKERHUB_USER=<user> IMAGE_TAG=<tag>
python3 ./scripts/set_dockerhub_images.py --user <user> --tag <tag> --root .
bash ./scripts/deploy_strict_order.sh
bash ./scripts/run_strict_validation.sh bottleneck-like high
```

For UBL tuning batches (10-15 minute style runs), keep port-forwards in auto-restart loops and run:

```bash
bash ./scripts/run_ubl_tuning_batch.sh
```

## Load Simulation Note

Yes, load is still simulated and required:

- simulator profile `high` is used for stressing Cassandra
- chaos profiles are injected while load is active

The standard strict run keeps enough pressure while staying within short experiment windows:

```bash
bash ./scripts/run_strict_validation.sh bottleneck-like high
```
