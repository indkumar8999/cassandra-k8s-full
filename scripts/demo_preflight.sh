#!/usr/bin/env bash
set -euo pipefail

EXPECTED_WORKERS="${EXPECTED_WORKERS:-3}"
STRICT_CONTEXT_BLOCKLIST_REGEX="${STRICT_CONTEXT_BLOCKLIST_REGEX:-^(docker-desktop|kind-.*|kind)$}"

die() {
  echo "[preflight][ERROR] $*" >&2
  exit 1
}

echo "[preflight] checking kubectl context"
CURRENT_CONTEXT="$(kubectl config current-context)"
echo "[preflight] current context: ${CURRENT_CONTEXT}"
if [[ "${CURRENT_CONTEXT}" =~ ${STRICT_CONTEXT_BLOCKLIST_REGEX} ]]; then
  die "context '${CURRENT_CONTEXT}' is not allowed for strict distributed runs"
fi

echo "[preflight] checking ready worker nodes"
READY_WORKERS="$(kubectl get nodes --no-headers | rg -v "control-plane|master" | rg " Ready " | wc -l | tr -d ' ')"
if [[ "${READY_WORKERS}" -lt "${EXPECTED_WORKERS}" ]]; then
  echo "[preflight] cluster nodes (fix NotReady / SchedulingDisabled before retrying):" >&2
  kubectl get nodes -o wide >&2
  die "need at least ${EXPECTED_WORKERS} Ready worker nodes (excluding control-plane), found ${READY_WORKERS}. Strict preflight matches a 3-node Cassandra spread; add or repair a worker."
fi

echo "[preflight] checking namespace"
kubectl get ns cassandra-lab >/dev/null

echo "[preflight] checking cassandra pods"
kubectl get pods -n cassandra-lab -l app=cassandra -o wide

echo "[preflight] checking cassandra desired replica count"
DESIRED_CASSANDRA_REPLICAS="$(kubectl get statefulset -n cassandra-lab cassandra -o jsonpath='{.spec.replicas}' | tr -d ' ')"
if [[ -z "${DESIRED_CASSANDRA_REPLICAS}" ]]; then
  die "unable to read desired cassandra replica count from statefulset/cassandra"
fi
CURRENT_CASSANDRA_PODS="$(kubectl get pods -n cassandra-lab -l app=cassandra --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${CURRENT_CASSANDRA_PODS}" -lt "${DESIRED_CASSANDRA_REPLICAS}" ]]; then
  die "cassandra pods not all created yet (${CURRENT_CASSANDRA_PODS}/${DESIRED_CASSANDRA_REPLICAS}). StatefulSet default is OrderedReady, so cassandra-1/2 will not be created until cassandra-0 becomes Ready. Wait a few minutes and retry."
fi

echo "[preflight] checking cassandra pod spread across distinct nodes"
DISTINCT_NODES="$(kubectl get pods -n cassandra-lab -l app=cassandra -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l | tr -d ' ')"
if [[ "${DISTINCT_NODES}" -lt 3 ]]; then
  die "cassandra pods are not distributed across 3 nodes (distinct nodes: ${DISTINCT_NODES})"
fi

echo "[preflight] checking cassandra ring health (all UN)"
RING_STATUS="$(kubectl exec -n cassandra-lab cassandra-0 -- env -u JVM_OPTS nodetool status)"
echo "${RING_STATUS}"
# Do not use `rg -c` / `grep -c` here: with pipefail they exit 1 when the count is 0 and abort the script.
UN_COUNT="$(printf '%s\n' "${RING_STATUS}" | awk '/^[[:space:]]*UN[[:space:]]/ { c++ } END { print c + 0 }')"
if [[ "${UN_COUNT}" -lt 3 ]]; then
  die "expected at least 3 UN nodes in ring, got ${UN_COUNT}"
fi

echo "[preflight] checking simulator"
kubectl get pods -n cassandra-lab -l app=cassandra-simulator

echo "[preflight] checking learner and chaos injector"
kubectl get pods -n cassandra-lab -l app=ubl-learner
kubectl get pods -n cassandra-lab -l app=chaos-injector

echo "[preflight] checking monitoring targets"
kubectl get podmonitors -n monitoring | rg "cassandra|simulator"

echo "[preflight] done"
