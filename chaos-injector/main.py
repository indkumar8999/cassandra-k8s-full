import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Optional

from flask import Flask, jsonify, request
from kubernetes import client, config
from kubernetes.client.rest import ApiException


app = Flask(__name__)

NAMESPACE = os.getenv("TARGET_NAMESPACE", "cassandra-lab")
CASSANDRA_LABEL = os.getenv("CASSANDRA_LABEL_SELECTOR", "app=cassandra")
SIMULATOR_LABEL = os.getenv("SIMULATOR_LABEL_SELECTOR", "app=cassandra-simulator")
STRESS_IMAGE = os.getenv("STRESS_IMAGE", "polinux/stress")
DEFAULT_DURATION_SEC = int(os.getenv("DEFAULT_FAULT_DURATION_SEC", "120"))
DEFAULT_CPU_WORKERS = int(os.getenv("DEFAULT_CPU_WORKERS", "2"))
DEFAULT_MEM_MB = int(os.getenv("DEFAULT_MEM_MB", "1024"))
DEFAULT_CPU_LOAD = int(os.getenv("DEFAULT_CPU_LOAD", "90"))
DEFAULT_BOTTLENECK_REPLICAS = int(os.getenv("DEFAULT_BOTTLENECK_REPLICAS", "2"))


def init_k8s():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()


init_k8s()
core = client.CoreV1Api()
apps = client.AppsV1Api()
batch = client.BatchV1Api()
networking = client.NetworkingV1Api()


@dataclass
class FaultRecord:
    profile: str
    started_at: float
    target: str
    params: Dict
    status: str
    command_start_ts: float
    verified_start_ts: Optional[float] = None
    command_stop_ts: Optional[float] = None
    verified_stop_ts: Optional[float] = None
    extra: Optional[Dict] = None


ACTIVE_FAULTS: Dict[str, FaultRecord] = {}


def _job_name(profile: str) -> str:
    return f"chaos-{profile}-{int(time.time())}"


def _build_stress_job(name: str, command: list[str], target_node_name: Optional[str]):
    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        containers=[
            client.V1Container(
                name="stress",
                image=STRESS_IMAGE,
                command=command,
                resources=client.V1ResourceRequirements(
                    limits={"cpu": "500m", "memory": "1500Mi"},
                    requests={"cpu": "100m", "memory": "128Mi"},
                ),
            )
        ],
    )
    if target_node_name:
        pod_spec.node_name = target_node_name

    return client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=NAMESPACE, labels={"app": "chaos-injector", "profile": name}),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=120,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "chaos-injector", "profile": name}),
                spec=pod_spec,
            ),
        ),
    )


def _pick_cassandra_pod():
    pods = core.list_namespaced_pod(namespace=NAMESPACE, label_selector=CASSANDRA_LABEL).items
    if not pods:
        raise RuntimeError("No Cassandra pods found for fault target.")
    pods_sorted = sorted(pods, key=lambda p: p.metadata.name)
    return pods_sorted[0]


def _create_network_congestion_policy(name: str):
    policy = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(name=name, namespace=NAMESPACE),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels={"app": "cassandra-simulator"}),
            policy_types=["Egress"],
            egress=[
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(match_labels={"kubernetes.io/metadata.name": "kube-system"})
                        )
                    ]
                )
            ],
        ),
    )
    networking.create_namespaced_network_policy(namespace=NAMESPACE, body=policy)


def _delete_network_policy(name: str):
    try:
        networking.delete_namespaced_network_policy(name=name, namespace=NAMESPACE)
    except ApiException as ex:
        if ex.status != 404:
            raise


def _delete_job(name: str):
    try:
        batch.delete_namespaced_job(name=name, namespace=NAMESPACE, propagation_policy="Foreground")
    except ApiException as ex:
        if ex.status != 404:
            raise


def _start_memleak(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", DEFAULT_DURATION_SEC))
    mem_mb = int(params.get("mem_mb", DEFAULT_MEM_MB))
    target_pod = _pick_cassandra_pod()
    job_name = _job_name("memleak-like")
    command = ["sh", "-c", f"stress --vm 1 --vm-bytes {mem_mb}M --timeout {duration}s"]
    batch.create_namespaced_job(namespace=NAMESPACE, body=_build_stress_job(job_name, command, target_pod.spec.node_name))

    return FaultRecord(
        profile="memleak-like",
        started_at=time.time(),
        target=target_pod.metadata.name,
        params={"duration_sec": duration, "mem_mb": mem_mb, "job_name": job_name, "node_name": target_pod.spec.node_name},
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _start_cpuhog(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", DEFAULT_DURATION_SEC))
    workers = int(params.get("cpu_workers", DEFAULT_CPU_WORKERS))
    target_pod = _pick_cassandra_pod()
    job_name = _job_name("cpuhog-like")
    command = ["sh", "-c", f"stress --cpu {workers} --timeout {duration}s"]
    batch.create_namespaced_job(namespace=NAMESPACE, body=_build_stress_job(job_name, command, target_pod.spec.node_name))

    return FaultRecord(
        profile="cpuhog-like",
        started_at=time.time(),
        target=target_pod.metadata.name,
        params={"duration_sec": duration, "cpu_workers": workers, "job_name": job_name, "node_name": target_pod.spec.node_name},
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _start_network_congestion(params: Dict) -> FaultRecord:
    policy_name = f"chaos-network-congestion-{int(time.time())}"
    _create_network_congestion_policy(policy_name)
    return FaultRecord(
        profile="network-congestion-like",
        started_at=time.time(),
        target=SIMULATOR_LABEL,
        params={"network_policy_name": policy_name},
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _start_bottleneck(params: Dict) -> FaultRecord:
    replicas = int(params.get("replicas", DEFAULT_BOTTLENECK_REPLICAS))
    sts = apps.read_namespaced_stateful_set(name="cassandra", namespace=NAMESPACE)
    original = int(sts.spec.replicas)
    patch = {"spec": {"replicas": replicas}}
    apps.patch_namespaced_stateful_set(name="cassandra", namespace=NAMESPACE, body=patch)
    return FaultRecord(
        profile="bottleneck-like",
        started_at=time.time(),
        target="statefulset/cassandra",
        params={"original_replicas": original, "new_replicas": replicas},
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _stop_fault(record: FaultRecord):
    if record.profile in {"memleak-like", "cpuhog-like"}:
        _delete_job(record.params["job_name"])
    elif record.profile == "network-congestion-like":
        _delete_network_policy(record.params["network_policy_name"])
    elif record.profile == "bottleneck-like":
        patch = {"spec": {"replicas": record.params["original_replicas"]}}
        apps.patch_namespaced_stateful_set(name="cassandra", namespace=NAMESPACE, body=patch)


@app.get("/health")
def health():
    return jsonify({"status": "up", "active_fault_count": len(ACTIVE_FAULTS)})


@app.get("/faults")
def faults():
    return jsonify({"active_faults": {k: asdict(v) for k, v in ACTIVE_FAULTS.items()}})


@app.post("/start_fault")
def start_fault():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", "").strip().lower()
    if profile in ACTIVE_FAULTS:
        return jsonify({"error": f"{profile} already active"}), 409

    try:
        if profile == "memleak-like":
            record = _start_memleak(body)
        elif profile == "cpuhog-like":
            record = _start_cpuhog(body)
        elif profile == "network-congestion-like":
            record = _start_network_congestion(body)
        elif profile == "bottleneck-like":
            record = _start_bottleneck(body)
        else:
            return jsonify({"error": "Unknown profile. Use memleak-like/cpuhog-like/network-congestion-like/bottleneck-like"}), 400
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    ACTIVE_FAULTS[profile] = record
    return jsonify({"message": "fault started", "fault": asdict(record)})


@app.post("/stop_fault")
def stop_fault():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", "").strip().lower()
    if profile not in ACTIVE_FAULTS:
        return jsonify({"error": f"{profile} not active"}), 404

    record = ACTIVE_FAULTS[profile]
    try:
        _stop_fault(record)
        record.command_stop_ts = time.time()
        record.verified_stop_ts = time.time()
        record.status = "stopped"
        payload = asdict(record)
        del ACTIVE_FAULTS[profile]
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    return jsonify({"message": "fault stopped", "fault": payload})


@app.post("/reset_all")
def reset_all():
    stopped = {}
    for profile in list(ACTIVE_FAULTS.keys()):
        record = ACTIVE_FAULTS[profile]
        try:
            _stop_fault(record)
            record.command_stop_ts = time.time()
            record.verified_stop_ts = time.time()
            record.status = "stopped"
            stopped[profile] = asdict(record)
            del ACTIVE_FAULTS[profile]
        except Exception as ex:
            stopped[profile] = {"error": str(ex)}

    return jsonify({"message": "reset complete", "stopped": stopped})


def main():
    app.run(host="0.0.0.0", port=8200, threaded=True)


if __name__ == "__main__":
    main()
