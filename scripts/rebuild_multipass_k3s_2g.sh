#!/usr/bin/env bash
set -euo pipefail

# Rebuild a strict 4-node k3s cluster on macOS using Multipass.
# This is destructive for the named instances.
# Default RAM is 4G per VM (override with VM_MEMORY=2G for tighter laptops).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CP_NAME="${CP_NAME:-cp1}"
WORKER_NAMES="${WORKER_NAMES:-w1 w2 w3}"
UBUNTU_IMAGE="${UBUNTU_IMAGE:-22.04}"
VM_CPUS="${VM_CPUS:-2}"
VM_MEMORY="${VM_MEMORY:-4G}"
VM_DISK="${VM_DISK:-20G}"
KUBECONFIG_OUT="${KUBECONFIG_OUT:-${ROOT_DIR}/artifacts/kubeconfig-multipass-k3s.yaml}"
RECREATE="${RECREATE:-true}"

ALL_NAMES="${CP_NAME} ${WORKER_NAMES}"

log() {
  echo "[k3s-rebuild] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[k3s-rebuild][ERROR] missing required command: $1" >&2
    exit 1
  }
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[k3s-rebuild][ERROR] this script is intended for macOS + Multipass" >&2
  echo "[k3s-rebuild][ERROR] for non-macOS use docs/strict-zero-cost-cluster.md" >&2
  exit 1
fi

require_cmd multipass
require_cmd kubectl
require_cmd curl
require_cmd awk
require_cmd sed
require_cmd mkdir
require_cmd rg

if [[ "${RECREATE}" != "true" ]]; then
  echo "[k3s-rebuild][ERROR] set RECREATE=true to acknowledge destructive rebuild" >&2
  exit 1
fi

log "rebuilding instances: ${ALL_NAMES}"

for name in ${ALL_NAMES}; do
  if multipass info "${name}" >/dev/null 2>&1; then
    log "stopping ${name}"
    multipass stop "${name}" || true
    log "deleting ${name}"
    multipass delete "${name}" || true
  fi
done

log "purging deleted instances"
multipass purge

log "launching control-plane ${CP_NAME} (${VM_MEMORY} RAM)"
multipass launch "${UBUNTU_IMAGE}" --name "${CP_NAME}" --cpus "${VM_CPUS}" --memory "${VM_MEMORY}" --disk "${VM_DISK}"

for worker in ${WORKER_NAMES}; do
  log "launching worker ${worker} (${VM_MEMORY} RAM)"
  multipass launch "${UBUNTU_IMAGE}" --name "${worker}" --cpus "${VM_CPUS}" --memory "${VM_MEMORY}" --disk "${VM_DISK}"
done

log "installing k3s server on ${CP_NAME}"
multipass exec "${CP_NAME}" -- bash -lc "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='--write-kubeconfig-mode 644 --node-name ${CP_NAME}' sh -"

CP_IP="$(multipass info "${CP_NAME}" | awk '/IPv4/{print $2; exit}')"
if [[ -z "${CP_IP}" ]]; then
  echo "[k3s-rebuild][ERROR] unable to resolve control-plane IP" >&2
  exit 1
fi

log "reading k3s node token"
K3S_TOKEN="$(multipass exec "${CP_NAME}" -- sudo cat /var/lib/rancher/k3s/server/node-token)"

for worker in ${WORKER_NAMES}; do
  log "joining worker ${worker}"
  multipass exec "${worker}" -- bash -lc "curl -sfL https://get.k3s.io | K3S_URL='https://${CP_IP}:6443' K3S_TOKEN='${K3S_TOKEN}' INSTALL_K3S_EXEC='--node-name ${worker}' sh -"
done

log "exporting kubeconfig to ${KUBECONFIG_OUT}"
mkdir -p "$(dirname "${KUBECONFIG_OUT}")"
multipass exec "${CP_NAME}" -- sudo cat /etc/rancher/k3s/k3s.yaml > "${KUBECONFIG_OUT}"
sed -i '' "s/127.0.0.1/${CP_IP}/g" "${KUBECONFIG_OUT}"

log "waiting for all nodes to report Ready"
for _ in $(seq 1 30); do
  READY_COUNT="$(kubectl --kubeconfig "${KUBECONFIG_OUT}" get nodes --no-headers 2>/dev/null | rg " Ready " | wc -l | tr -d ' ')"
  if [[ "${READY_COUNT}" -ge 4 ]]; then
    break
  fi
  sleep 5
done

READY_COUNT="$(kubectl --kubeconfig "${KUBECONFIG_OUT}" get nodes --no-headers 2>/dev/null | rg " Ready " | wc -l | tr -d ' ')"
if [[ "${READY_COUNT}" -lt 4 ]]; then
  echo "[k3s-rebuild][ERROR] expected 4 Ready nodes, found ${READY_COUNT}" >&2
  kubectl --kubeconfig "${KUBECONFIG_OUT}" get nodes -o wide || true
  exit 1
fi

log "current node status"
kubectl --kubeconfig "${KUBECONFIG_OUT}" get nodes -o wide

cat <<EOF

[k3s-rebuild] cluster ready
[k3s-rebuild] next steps:
  export KUBECONFIG="${KUBECONFIG_OUT}"
  kubectl config current-context
  cd "${ROOT_DIR}"
  bash ./scripts/deploy_strict_order.sh
  bash ./scripts/run_strict_validation.sh bottleneck-like high
EOF
