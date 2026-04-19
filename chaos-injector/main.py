import os
import secrets
import shlex
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from flask import Flask, jsonify, request
from kubernetes import client, config
from kubernetes.client.rest import ApiException


app = Flask(__name__)

NAMESPACE = os.getenv("TARGET_NAMESPACE", "cassandra-lab")
CASSANDRA_LABEL = os.getenv("CASSANDRA_LABEL_SELECTOR", "app=cassandra")
SIMULATOR_LABEL = os.getenv("SIMULATOR_LABEL_SELECTOR", "app=cassandra-simulator")
DEFAULT_DURATION_SEC = int(os.getenv("DEFAULT_FAULT_DURATION_SEC", "120"))
DEFAULT_BOTTLENECK_REPLICAS = int(os.getenv("DEFAULT_BOTTLENECK_REPLICAS", "2"))

# cassandra-stress workload fault config
STRESS_CASSANDRA_IMAGE = os.getenv("STRESS_CASSANDRA_IMAGE", "cassandra:4.1")
CASSANDRA_STRESS_CONTACT_POINT = os.getenv(
    "CASSANDRA_STRESS_CONTACT_POINT", "cassandra-client.cassandra-lab.svc.cluster.local"
)
CASSANDRA_STRESS_PORT = int(os.getenv("CASSANDRA_STRESS_PORT", "9042"))
# In the official cassandra image, cassandra-stress is not on PATH.
CASSANDRA_STRESS_BIN = os.getenv("CASSANDRA_STRESS_BIN", "/opt/cassandra/tools/bin/cassandra-stress")
# Consistency level for cassandra-stress commands (default matches cassandra-stress defaults).
CASSANDRA_STRESS_CL = os.getenv("CASSANDRA_STRESS_CL", "LOCAL_ONE")

# cassandra-stress Job cgroup sizing (high limits so each client can actually drive the cluster).
STRESS_JOB_CPU_REQUEST = os.getenv("STRESS_JOB_CPU_REQUEST", "1000m")
STRESS_JOB_CPU_LIMIT = os.getenv("STRESS_JOB_CPU_LIMIT", "4")
STRESS_JOB_MEM_REQUEST = os.getenv("STRESS_JOB_MEM_REQUEST", "1Gi")
STRESS_JOB_MEM_LIMIT = os.getenv("STRESS_JOB_MEM_LIMIT", "3Gi")

# Run N identical cassandra-stress Jobs in parallel (separate pods = separate TCP flows; much higher cluster CPU).
DEFAULT_STRESS_PARALLEL_JOBS = int(os.getenv("DEFAULT_STRESS_PARALLEL_JOBS", "1"))
MAX_STRESS_PARALLEL_JOBS = int(os.getenv("MAX_STRESS_PARALLEL_JOBS", "8"))

# Aggressive defaults (override per request or per-env for lab tuning)
DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS", "130"))
DEFAULT_CASSANDRA_STRESS_HOT_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_HOT_THREADS", "220"))
DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS", "280"))
DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS", "800"))
DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS", "200"))
DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS", "170"))
DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS", "340"))
DEFAULT_CASSANDRA_STRESS_TTL_SEC = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_SEC", "60"))
DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC", "90"))

# default population ranges for different recipes
DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END", "5000000"))
DEFAULT_CASSANDRA_STRESS_POP_HOT_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_HOT_END", "100"))
DEFAULT_CASSANDRA_STRESS_POP_MIXED_SKEW_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_MIXED_SKEW_END", "500"))


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


def _build_cassandra_stress_job(name: str, command: list[str]):
    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        containers=[
            client.V1Container(
                name="cassandra-stress",
                image=STRESS_CASSANDRA_IMAGE,
                command=command,
                resources=client.V1ResourceRequirements(
                    limits={"cpu": STRESS_JOB_CPU_LIMIT, "memory": STRESS_JOB_MEM_LIMIT},
                    requests={"cpu": STRESS_JOB_CPU_REQUEST, "memory": STRESS_JOB_MEM_REQUEST},
                ),
            )
        ],
    )

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


def _delete_stress_jobs(record: FaultRecord):
    names: List[str] = list(record.params.get("job_names") or [])
    if not names and record.params.get("job_name"):
        names = [record.params["job_name"]]
    for n in names:
        _delete_job(n)


def _resolve_parallel_jobs(params: Dict) -> int:
    raw = int(params.get("parallel_jobs", DEFAULT_STRESS_PARALLEL_JOBS))
    return max(1, min(raw, MAX_STRESS_PARALLEL_JOBS))


def _cassandra_stress_base_args(*, duration_sec: int, threads: int, pop_start: int, pop_end: int, col: str, rf: int) -> list[str]:
    return [
        f"duration={duration_sec}s",
        f"cl={CASSANDRA_STRESS_CL}",
        "-node",
        CASSANDRA_STRESS_CONTACT_POINT,
        "-port",
        f"native={CASSANDRA_STRESS_PORT}",
        "-rate",
        f"threads={threads}",
        "-pop",
        f"seq={pop_start}..{pop_end}",
        "-schema",
        f"replication(strategy=SimpleStrategy,factor={rf})",
        "-col",
        *shlex.split(col),
        "-mode",
        "cql3",
        "native",
        "-log",
        "interval=5s",
    ]


def _cmd_baseline_normal(*, duration_sec: int, threads: int, pop_end: int, rf: int) -> list[str]:
    # cassandra-stress mixed ratio(write=5,read=5) ...
    return [
        CASSANDRA_STRESS_BIN,
        "mixed",
        "ratio(write=5,read=5)",
        *_cassandra_stress_base_args(
            duration_sec=duration_sec,
            threads=threads,
            pop_start=1,
            pop_end=pop_end,
            col="n=FIXED(1) size=FIXED(512)",
            rf=rf,
        ),
    ]


def _cmd_anomaly_hot_partition(*, duration_sec: int, threads: int, rf: int) -> list[str]:
    return [
        CASSANDRA_STRESS_BIN,
        "write",
        *_cassandra_stress_base_args(
            duration_sec=duration_sec,
            threads=threads,
            pop_start=1,
            pop_end=int(os.getenv("CASSANDRA_STRESS_POP_HOT_END", str(DEFAULT_CASSANDRA_STRESS_POP_HOT_END))),
            col="n=FIXED(1) size=FIXED(512)",
            rf=rf,
        ),
    ]


def _cmd_anomaly_compaction_pressure(*, duration_sec: int, threads: int, pop_end: int, rf: int) -> list[str]:
    return [
        CASSANDRA_STRESS_BIN,
        "write",
        *_cassandra_stress_base_args(
            duration_sec=duration_sec,
            threads=threads,
            pop_start=1,
            pop_end=pop_end,
            col="n=FIXED(8) size=FIXED(2048)",
            rf=rf,
        ),
    ]


def _cmd_anomaly_concurrency_spike(*, duration_sec: int, threads: int, pop_end: int, rf: int) -> list[str]:
    return [
        CASSANDRA_STRESS_BIN,
        "write",
        *_cassandra_stress_base_args(
            duration_sec=duration_sec,
            threads=threads,
            pop_start=1,
            pop_end=pop_end,
            col="n=FIXED(1) size=FIXED(1024)",
            rf=rf,
        ),
    ]


def _cmd_anomaly_mixed_skew_large_payload(*, duration_sec: int, threads: int, rf: int) -> list[str]:
    return [
        CASSANDRA_STRESS_BIN,
        "mixed",
        "ratio(write=7,read=3)",
        *_cassandra_stress_base_args(
            duration_sec=duration_sec,
            threads=threads,
            pop_start=1,
            pop_end=int(os.getenv("CASSANDRA_STRESS_POP_MIXED_SKEW_END", str(DEFAULT_CASSANDRA_STRESS_POP_MIXED_SKEW_END))),
            col="n=FIXED(5) size=EXP(256..4096)",
            rf=rf,
        ),
    ]


def _cmd_anomaly_ttl_tombstone_script(
    *,
    write_duration_sec: int,
    read_duration_sec: int,
    write_threads: int,
    read_threads: int,
    pop_end: int,
    ttl_sec: int,
    delay_sec: int,
    rf: int,
) -> list[str]:
    # Two-phase: write with ttl, wait for expiry window, then read.
    write_cmd = [
        CASSANDRA_STRESS_BIN,
        "write",
        *_cassandra_stress_base_args(
            duration_sec=write_duration_sec,
            threads=write_threads,
            pop_start=1,
            pop_end=pop_end,
            col="n=FIXED(2) size=FIXED(512)",
            rf=rf,
        ),
        "-insert",
        f"ttl={ttl_sec}",
    ]
    read_cmd = [
        CASSANDRA_STRESS_BIN,
        "read",
        *_cassandra_stress_base_args(
            duration_sec=read_duration_sec,
            threads=read_threads,
            pop_start=1,
            pop_end=pop_end,
            # reads don't need -col, but cassandra-stress accepts it; keep base args stable by reusing a small column def
            col="n=FIXED(1) size=FIXED(512)",
            rf=rf,
        ),
    ]

    script = " ".join(shlex.quote(x) for x in write_cmd) + f" && sleep {int(delay_sec)} && " + " ".join(
        shlex.quote(x) for x in read_cmd
    )
    return ["sh", "-lc", script]


def _start_cassandra_stress_job(params: Dict, *, profile_name: str, command: list[str]) -> FaultRecord:
    parallel = _resolve_parallel_jobs(params)
    base = f"chaos-{int(time.time())}-{secrets.token_hex(3)}"
    job_names = [f"{base}-{i}" for i in range(parallel)]
    for job_name in job_names:
        batch.create_namespaced_job(namespace=NAMESPACE, body=_build_cassandra_stress_job(job_name, command))
    return FaultRecord(
        profile=profile_name,
        started_at=time.time(),
        target=CASSANDRA_STRESS_CONTACT_POINT,
        params={
            "job_names": job_names,
            "job_name": job_names[0],
            "parallel_jobs": parallel,
            "contact_point": CASSANDRA_STRESS_CONTACT_POINT,
            "port": CASSANDRA_STRESS_PORT,
            "image": STRESS_CASSANDRA_IMAGE,
            "request": params,
            "command": command,
        },
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _start_baseline_normal(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS))
    pop_end = int(params.get("pop_end", DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(params, profile_name="baseline-normal", command=_cmd_baseline_normal(duration_sec=duration, threads=threads, pop_end=pop_end, rf=rf))


def _start_anomaly_hot_partition(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_HOT_THREADS))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(params, profile_name="anomaly-hot-partition", command=_cmd_anomaly_hot_partition(duration_sec=duration, threads=threads, rf=rf))


def _start_anomaly_compaction_pressure(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS))
    pop_end = int(params.get("pop_end", DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(
        params,
        profile_name="anomaly-compaction-pressure",
        command=_cmd_anomaly_compaction_pressure(duration_sec=duration, threads=threads, pop_end=pop_end, rf=rf),
    )



def _start_anomaly_concurrency_spike(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 180))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS))
    pop_end = int(params.get("pop_end", DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(
        params,
        profile_name="anomaly-concurrency-spike",
        command=_cmd_anomaly_concurrency_spike(duration_sec=duration, threads=threads, pop_end=pop_end, rf=rf),
    )

# Custom short CPU spike fault (busybox job with busy loop)
def _start_short_cpu_spike(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 2))
    parallel = int(params.get("parallel_jobs", 1))
    base = f"short-cpu-spike-{int(time.time())}-{secrets.token_hex(3)}"
    job_names = [f"{base}-{i}" for i in range(parallel)]
    command = ["sh", "-c", f"echo Spiking CPU for {duration}s; timeout {duration} sh -c 'while :; do :; done'"]
    jobs = []
    for job_name in job_names:
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="cpu-spike",
                    image="busybox",
                    command=command,
                    resources=client.V1ResourceRequirements(
                        limits={"cpu": "2", "memory": "128Mi"},
                        requests={"cpu": "500m", "memory": "64Mi"},
                    ),
                )
            ],
        )
        job = client.V1Job(
            metadata=client.V1ObjectMeta(name=job_name, namespace=NAMESPACE, labels={"app": "chaos-injector", "profile": "short-cpu-spike"}),
            spec=client.V1JobSpec(
                backoff_limit=0,
                ttl_seconds_after_finished=60,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels={"app": "chaos-injector", "profile": "short-cpu-spike"}),
                    spec=pod_spec,
                ),
            ),
        )
        batch.create_namespaced_job(namespace=NAMESPACE, body=job)
        jobs.append(job)
    return FaultRecord(
        profile="short-cpu-spike",
        started_at=time.time(),
        target="busybox",
        params={
            "job_names": job_names,
            "parallel_jobs": parallel,
            "request": params,
            "command": command,
        },
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _start_anomaly_ttl_tombstone(params: Dict) -> FaultRecord:
    write_duration = int(params.get("write_duration_sec", 240))
    read_duration = int(params.get("read_duration_sec", 180))
    write_threads = int(params.get("write_threads", DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS))
    read_threads = int(params.get("read_threads", DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS))
    pop_end = int(params.get("pop_end", 2000000))
    ttl_sec = int(params.get("ttl_sec", DEFAULT_CASSANDRA_STRESS_TTL_SEC))
    delay_sec = int(params.get("delay_sec", DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(
        params,
        profile_name="anomaly-ttl-tombstone",
        command=_cmd_anomaly_ttl_tombstone_script(
            write_duration_sec=write_duration,
            read_duration_sec=read_duration,
            write_threads=write_threads,
            read_threads=read_threads,
            pop_end=pop_end,
            ttl_sec=ttl_sec,
            delay_sec=delay_sec,
            rf=rf,
        ),
    )


def _start_anomaly_mixed_skew_large_payload(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS))
    rf = int(params.get("replication_factor", 3))
    return _start_cassandra_stress_job(
        params,
        profile_name="anomaly-mixed-skew-large-payload",
        command=_cmd_anomaly_mixed_skew_large_payload(duration_sec=duration, threads=threads, rf=rf),
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
    if record.profile in {
        "baseline-normal",
        "anomaly-hot-partition",
        "anomaly-compaction-pressure",
        "anomaly-concurrency-spike",
        "anomaly-ttl-tombstone",
        "anomaly-mixed-skew-large-payload",
        "short-cpu-spike",
        # aliases retained for compatibility
        "cpuhog-like",
        "memleak-like",
    }:
        _delete_stress_jobs(record)
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
        if profile == "baseline-normal":
            record = _start_baseline_normal(body)
        elif profile == "anomaly-hot-partition":
            record = _start_anomaly_hot_partition(body)
        elif profile == "anomaly-compaction-pressure":
            record = _start_anomaly_compaction_pressure(body)
        elif profile == "anomaly-concurrency-spike":
            record = _start_anomaly_concurrency_spike(body)
        elif profile == "anomaly-ttl-tombstone":
            record = _start_anomaly_ttl_tombstone(body)
        elif profile == "anomaly-mixed-skew-large-payload":
            record = _start_anomaly_mixed_skew_large_payload(body)
        elif profile == "short-cpu-spike":
            record = _start_short_cpu_spike(body)
        elif profile == "cpuhog-like":
            # Compatibility alias
            record = _start_anomaly_concurrency_spike(body)
            record.profile = "cpuhog-like"
        elif profile == "memleak-like":
            # Compatibility alias
            record = _start_anomaly_compaction_pressure(body)
            record.profile = "memleak-like"
        elif profile == "network-congestion-like":
            record = _start_network_congestion(body)
        elif profile == "bottleneck-like":
            record = _start_bottleneck(body)
        else:
            return (
                jsonify(
                    {
                        "error": "Unknown profile.",
                        "valid_profiles": [
                            "baseline-normal",
                            "anomaly-hot-partition",
                            "anomaly-compaction-pressure",
                            "anomaly-concurrency-spike",
                            "anomaly-ttl-tombstone",
                            "anomaly-mixed-skew-large-payload",
                            "short-cpu-spike",
                            "cpuhog-like",
                            "memleak-like",
                            "network-congestion-like",
                            "bottleneck-like",
                        ],
                    }
                ),
                400,
            )
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    ACTIVE_FAULTS[profile] = record
    return jsonify({"message": "fault started", "fault": asdict(record)})


@app.post("/stop_fault")
def stop_fault():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", "").strip().lower()
    # Idempotent: ACTIVE_FAULTS is in-memory only; after pod restart or external reset, stop must not fail the scenario runner.
    if profile not in ACTIVE_FAULTS:
        return jsonify({"message": "fault not active (already stopped)", "fault": None, "profile": profile})

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
