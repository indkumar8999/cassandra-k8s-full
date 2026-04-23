import os
import secrets
import shlex
import threading
import time
import re
from dataclasses import dataclass, asdict
from typing import Callable, Dict, Iterable, Iterator, List, Optional
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)


from flask import Flask, jsonify, request
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest


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
STRESS_JOB_TTL_SECONDS_AFTER_FINISHED = int(os.getenv("STRESS_JOB_TTL_SECONDS_AFTER_FINISHED", "900"))

# Aggressive defaults (override per request or per-env for lab tuning)
DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS", "100"))
DEFAULT_CASSANDRA_STRESS_HOT_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_HOT_THREADS", "220"))
DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS", "280"))
# Concurrency-spike profile matches canonical lab one-liner: write, 500 threads, pop 1..5M, n=1 size=FIXED(1024), RF=3, LOCAL_ONE, log 5s, default 180s duration.
DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS", "2000"))
DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS", "2000"))
DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS", "1700"))
DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS = int(os.getenv("DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS", "500"))
DEFAULT_CASSANDRA_STRESS_TTL_SEC = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_SEC", "60"))
DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC = int(os.getenv("DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC", "90"))

# default population ranges for different recipes
DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END", "1000000"))
DEFAULT_CASSANDRA_STRESS_POP_HOT_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_HOT_END", "100"))
DEFAULT_CASSANDRA_STRESS_POP_MIXED_SKEW_END = int(os.getenv("DEFAULT_CASSANDRA_STRESS_POP_MIXED_SKEW_END", "500"))

# cassandra-stress user profile (ConfigMap chaos-university-stress-profile, key university-profile.yaml → /profiles/...)
UNIVERSITY_STRESS_CONFIGMAP = os.getenv("UNIVERSITY_STRESS_CONFIGMAP", "chaos-university-stress-profile")
DEFAULT_UNIVERSITY_STRESS_THREADS = int(os.getenv("DEFAULT_UNIVERSITY_STRESS_THREADS", "120"))
DEFAULT_UNIVERSITY_STRESS_OPS = os.getenv(
    "DEFAULT_UNIVERSITY_STRESS_OPS",
    "ops(insert=4,course_section_enrollments=3,by_student_id=2,by_teacher_id=2,student_courses_lookup=1)",
)
DEFAULT_UNIVERSITY_TRUNCATE = os.getenv("DEFAULT_UNIVERSITY_TRUNCATE", "truncate=once")

# NoSQLBench (NB5) — separate Job path from cassandra-stress; metrics via --report-prompush-to when configured.
# Official image entrypoint is `java ... -jar nb5.jar`; do not use command=["nb5", ...] (nb5 is not on PATH).
NOSQLBENCH_IMAGE = os.getenv("NOSQLBENCH_IMAGE", "nosqlbench/nosqlbench:5.17.9")
NOSQLBENCH_JAVA_BIN = os.getenv("NOSQLBENCH_JAVA_BIN", "java").strip() or "java"
NOSQLBENCH_JAR_PATH = os.getenv("NOSQLBENCH_JAR_PATH", "/nb5.jar").strip()
NOSQLBENCH_JAVA_OPTS = os.getenv("NOSQLBENCH_JAVA_OPTS", "").strip()
NOSQLBENCH_WORKDIR = os.getenv("NOSQLBENCH_WORKDIR", "").strip()
NOSQLBENCH_SCENARIO_CONFIGMAP = os.getenv("NOSQLBENCH_SCENARIO_CONFIGMAP", "chaos-nosqlbench-scenarios")
NOSQLBENCH_SCENARIO_MOUNT_PATH = os.getenv("NOSQLBENCH_SCENARIO_MOUNT_PATH", "/scenarios")
# Must match Cassandra snitch DC (see k8s/cassandra/cassandra-config.yaml CASSANDRA_DC, e.g. DC1).
CASSANDRA_LOCAL_DC = os.getenv("CASSANDRA_LOCAL_DC", "DC1")
NOSQLBENCH_HOSTS = os.getenv("NOSQLBENCH_HOSTS", "").strip()
NOSQLBENCH_CYCLES_MULT = int(os.getenv("NOSQLBENCH_CYCLES_MULT", "400"))

# Optional: persist HDR histostats (p95/p99 in ns) for each NB Job and export them via a sidecar.
# Requires:
# - PVC named by NOSQLBENCH_HISTOSTATS_PVC (default: nosqlbench-histostats-pvc) in the target namespace
# - ConfigMap named by NOSQLBENCH_HISTOSTATS_EXPORTER_CONFIGMAP (default: nosqlbench-histostats-exporter)
NOSQLBENCH_HISTOSTATS_ENABLED = os.getenv("NOSQLBENCH_HISTOSTATS_ENABLED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
NOSQLBENCH_HISTOSTATS_INTERVAL = os.getenv("NOSQLBENCH_HISTOSTATS_INTERVAL", "10s").strip() or "10s"
NOSQLBENCH_HISTOSTATS_PVC = os.getenv("NOSQLBENCH_HISTOSTATS_PVC", "nosqlbench-histostats-pvc").strip()
NOSQLBENCH_HISTOSTATS_MOUNT_PATH = os.getenv("NOSQLBENCH_HISTOSTATS_MOUNT_PATH", "/work").strip() or "/work"
NOSQLBENCH_HISTOSTATS_EXPORTER_CONFIGMAP = os.getenv(
    "NOSQLBENCH_HISTOSTATS_EXPORTER_CONFIGMAP", "nosqlbench-histostats-exporter"
).strip()


def _nb_prompush_base() -> str:
    """Prometheus Pushgateway base URL (read from env each time NB args are built)."""
    return (os.environ.get("PROMPUSH_URL") or "").strip()


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

STRESS_P95_MS = Gauge(
    "cassandra_stress_p95_ms",
    "cassandra-stress 95th percentile latency (ms) for latest interval sample",
    labelnames=("profile", "job_name"),
)
STRESS_P99_MS = Gauge(
    "cassandra_stress_p99_ms",
    "cassandra-stress 99th percentile latency (ms) for latest interval sample",
    labelnames=("profile", "job_name"),
)

# Stop flags for background log streamers keyed by profile.
_METRICS_STOP: Dict[str, threading.Event] = {}


def _get_job_pod_name(namespace: str, job_name: str) -> str:
    pods = core.list_namespaced_pod(
        namespace=namespace,
        label_selector=f"job-name={job_name}",
    ).items
    if not pods:
        raise RuntimeError(f"No pod found yet for job {job_name}")
    # If multiple pods exist (retries), pick the newest.
    pods = sorted(pods, key=lambda p: p.metadata.creation_timestamp or 0, reverse=True)
    return pods[0].metadata.name


def stream_job_logs(namespace: str, job_name: str, *, since_seconds: Optional[int] = None):
    """
    Stream stdout from the Pod created by a Kubernetes Job.

    Intended for streaming cassandra-stress interval stats (e.g. -log interval=1s).
    Reconnects automatically on transient failures / pod restarts.
    """
    while True:
        pod_name: Optional[str] = None
        # Wait for the Job's Pod to appear.
        for _ in range(60):
            try:
                pod_name = _get_job_pod_name(namespace, job_name)
                break
            except RuntimeError:
                time.sleep(1)

        if not pod_name:
            raise RuntimeError(f"Timed out waiting for pod of job {job_name}")

        try:
            resp = core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container="cassandra-stress",
                follow=True,
                timestamps=True,
                since_seconds=since_seconds,
                _preload_content=False,
            )
            for raw in resp.stream():
                yield raw.decode("utf-8", errors="ignore").rstrip()

            # If stream ends naturally, loop and reattach.
            since_seconds = 10
            time.sleep(1)
        except ApiException:
            since_seconds = 10
            time.sleep(2)

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


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

# Active faults started via /start_nosqlbench (independent dict so profiles can mirror cassandra-stress names).
ACTIVE_NB_FAULTS: Dict[str, FaultRecord] = {}


def _university_stress_nodes() -> str:
    ns = NAMESPACE
    return os.getenv(
        "UNIVERSITY_STRESS_NODES",
        (
            f"cassandra-0.cassandra.{ns}.svc.cluster.local,"
            f"cassandra-1.cassandra.{ns}.svc.cluster.local,"
            f"cassandra-2.cassandra.{ns}.svc.cluster.local"
        ),
    )


def _build_cassandra_stress_job(name: str, command: list[str], *, mount_university_profile: bool = False):
    volumes: List[client.V1Volume] = []
    mounts: List[client.V1VolumeMount] = []
    if mount_university_profile:
        vname = "chaos-university-profile"
        volumes.append(
            client.V1Volume(
                name=vname,
                config_map=client.V1ConfigMapVolumeSource(
                    name=UNIVERSITY_STRESS_CONFIGMAP,
                    items=[client.V1KeyToPath(key="university-profile.yaml", path="university-profile.yaml")],
                ),
            )
        )
        mounts.append(
            client.V1VolumeMount(
                name=vname,
                mount_path="/profiles/university-profile.yaml",
                sub_path="university-profile.yaml",
                read_only=True,
            )
        )

    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        volumes=volumes or None,
        containers=[
            client.V1Container(
                name="cassandra-stress",
                image=STRESS_CASSANDRA_IMAGE,
                command=command,
                volume_mounts=mounts or None,
                resources=client.V1ResourceRequirements(
                    limits={"cpu": STRESS_JOB_CPU_LIMIT, "memory": STRESS_JOB_MEM_LIMIT},
                    requests={"cpu": STRESS_JOB_CPU_REQUEST, "memory": STRESS_JOB_MEM_REQUEST},
                ),
            )
        ],
    )

    # IMPORTANT: stress Job pods must NOT share the same selector label as the chaos-injector API Deployment.
    # Otherwise Service/PodMonitor selectors will also match stress pods (which don't listen on :8200),
    # causing flaky port-forwarding and scrape failures.
    stress_labels = {"app": "cassandra-stress", "managed_by": "chaos-injector", "profile": name}

    return client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=NAMESPACE, labels=stress_labels),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=STRESS_JOB_TTL_SECONDS_AFTER_FINISHED,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=stress_labels),
                spec=pod_spec,
            ),
        ),
    )


def _nb_hosts_for_load() -> str:
    if NOSQLBENCH_HOSTS:
        return NOSQLBENCH_HOSTS
    return CASSANDRA_STRESS_CONTACT_POINT


def _nb_keyspace_token(job_name: str) -> str:
    s = job_name.replace("-", "_").lower()
    if not s or not (s[0].isalpha()):
        s = "nb_" + s
    return s[:48]


def _nb_main_cycles(duration_sec: int, threads: int) -> int:
    t = max(1, int(threads))
    return max(50_000, min(2_000_000_000, int(duration_sec) * t * NOSQLBENCH_CYCLES_MULT))


def _nb_rampup_cycles(duration_sec: int, threads: int) -> int:
    return max(500, min(2_000_000, int(duration_sec) * max(1, int(threads)) * 20))


def _nb_prompush_report_url(profile_name: str, job_name: str, job_index: int) -> str:
    """
    NB5 PromPushReporter POSTs to the given URI via Java HttpClient (http/https only).

    - ``victoria:plain:host:port`` / ``victoria:tls:host:port`` — expanded here to VictoriaMetrics
      ``/api/v1/import/prometheus/metrics/job/nosqlbench/instance/...`` (NB 5.17.x does *not*
      accept the ``victoria:`` scheme; it would throw ``invalid URI scheme victoria``).
    - ``http(s)://...`` without a push path — append Pushgateway-style ``/metrics/job/...`` (PG
      often rejects NB OpenMetrics with HTTP 400; prefer VM shorthand above).
    - URLs that already include ``/metrics/job/`` or VM import ``.../import/prometheus/metrics/job/``
      are left unchanged.
    """
    base = _nb_prompush_base().strip().rstrip("/")
    if not base:
        return ""
    low = base.lower()
    if "/metrics/job/" in base or "/api/v1/import/prometheus/metrics/job/" in low:
        return base

    safe_prof = re.sub(r"[^a-zA-Z0-9_-]+", "_", profile_name)[:40] or "nb"
    safe_job = re.sub(r"[^a-zA-Z0-9_-]+", "_", job_name)[:80] or "job"
    inst = f"{safe_prof}_{job_index}_{safe_job}"[:200]

    m = re.match(r"(?i)victoria:(plain|tls):(.+)$", base)
    if m:
        mode, hostport = m.group(1).lower(), m.group(2).strip().rstrip("/")
        scheme = "https" if mode == "tls" else "http"
        vm_base = f"{scheme}://{hostport}"
        return f"{vm_base}/api/v1/import/prometheus/metrics/job/nosqlbench/instance/{inst}"

    if "/api/v1/import/prometheus" in low:
        return base

    return f"{base}/metrics/job/nosqlbench/instance/{inst}"


def _nb_prometheus_push_args(profile_name: str, job_name: str, job_index: int) -> List[str]:
    if not _nb_prompush_base():
        return []
    safe_prof = re.sub(r"[^a-zA-Z0-9_]+", "_", profile_name)[:40]
    safe_job = re.sub(r"[^a-zA-Z0-9_]+", "_", job_name)[:40]
    prefix = f"nb_{safe_prof}_{safe_job}_{job_index}"
    return [
        "--report-prompush-to",
        _nb_prompush_report_url(profile_name, job_name, job_index),
        "--metrics-prefix",
        prefix,
    ]


def _nb_java_command_prefix() -> List[str]:
    """Argv prefix to run the NB5 jar (matches nosqlbench/nosqlbench Docker layout)."""
    extra = shlex.split(NOSQLBENCH_JAVA_OPTS) if NOSQLBENCH_JAVA_OPTS else []
    return [NOSQLBENCH_JAVA_BIN, *extra, "-jar", NOSQLBENCH_JAR_PATH]


def _nb_shell_java_invocation(nb_args: List[str]) -> str:
    """Single shell-safe command line: java ... -jar nb5.jar <nb_args...>."""
    return " ".join(shlex.quote(x) for x in (*_nb_java_command_prefix(), *nb_args))


def _build_nosqlbench_job(name: str, command: List[str]):
    """Kubernetes Job running NoSQLBench (NB5). Uses a distinct app= label so PodMonitors for chaos-injector do not match."""
    volumes: List[client.V1Volume] = [
        client.V1Volume(
            name="nosqlbench-scenarios",
            config_map=client.V1ConfigMapVolumeSource(name=NOSQLBENCH_SCENARIO_CONFIGMAP),
        )
    ]
    mounts: List[client.V1VolumeMount] = [
        client.V1VolumeMount(
            name="nosqlbench-scenarios",
            mount_path=NOSQLBENCH_SCENARIO_MOUNT_PATH,
            read_only=True,
        )
    ]

    exporter_container: Optional[client.V1Container] = None
    if NOSQLBENCH_HISTOSTATS_ENABLED:
        volumes.append(
            client.V1Volume(
                name="nosqlbench-histostats",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=NOSQLBENCH_HISTOSTATS_PVC),
            )
        )
        mounts.append(
            client.V1VolumeMount(
                name="nosqlbench-histostats",
                mount_path=NOSQLBENCH_HISTOSTATS_MOUNT_PATH,
                read_only=False,
            )
        )
        volumes.append(
            client.V1Volume(
                name="nosqlbench-histostats-exporter",
                config_map=client.V1ConfigMapVolumeSource(name=NOSQLBENCH_HISTOSTATS_EXPORTER_CONFIGMAP),
            )
        )
        exporter_mount = client.V1VolumeMount(
            name="nosqlbench-histostats-exporter",
            mount_path="/exporter",
            read_only=True,
        )
        exporter_env = [
            client.V1EnvVar(
                name="NB_JOB_NAME",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="metadata.labels['job-name']")
                ),
            ),
            client.V1EnvVar(
                name="NB_PROFILE",
                value_from=client.V1EnvVarSource(
                    field_ref=client.V1ObjectFieldSelector(field_path="metadata.labels['profile']")
                ),
            ),
            client.V1EnvVar(name="NB_HISTOSTATS_ROOT", value=NOSQLBENCH_HISTOSTATS_MOUNT_PATH),
            client.V1EnvVar(name="NB_HISTOSTATS_FILENAME", value="hdrstats.csv"),
        ]
        exporter_container = client.V1Container(
            name="histostats-exporter",
            image="python:3.12-slim",
            command=["python", "-u", "/exporter/exporter.py"],
            env=exporter_env,
            ports=[client.V1ContainerPort(container_port=9406, name="nb-hdrstats")],
            volume_mounts=[
                exporter_mount,
                client.V1VolumeMount(
                    name="nosqlbench-histostats",
                    mount_path=NOSQLBENCH_HISTOSTATS_MOUNT_PATH,
                    read_only=True,
                ),
            ],
            resources=client.V1ResourceRequirements(
                requests={"cpu": "20m", "memory": "64Mi"},
                limits={"cpu": "200m", "memory": "256Mi"},
            ),
        )
    # TTL recipe uses sh -lc "..."; normal jobs use java -jar nb5.jar <args...>.
    # If histostats are enabled, wrap with a shell so we can mkdir the per-job folder.
    if NOSQLBENCH_HISTOSTATS_ENABLED:
        per_job_dir = f"{NOSQLBENCH_HISTOSTATS_MOUNT_PATH}/{name}"
        hist_arg = f"{per_job_dir}/hdrstats.csv:.*:{NOSQLBENCH_HISTOSTATS_INTERVAL}"
        nb_cmd = _nb_shell_java_invocation([*command, "--log-histostats", hist_arg])
        nb_container = client.V1Container(
            name="nosqlbench",
            image=NOSQLBENCH_IMAGE,
            command=["sh", "-lc", f"mkdir -p {shlex.quote(per_job_dir)} && exec {nb_cmd}"],
            working_dir=NOSQLBENCH_WORKDIR or None,
            volume_mounts=mounts,
            resources=client.V1ResourceRequirements(
                limits={"cpu": STRESS_JOB_CPU_LIMIT, "memory": STRESS_JOB_MEM_LIMIT},
                requests={"cpu": STRESS_JOB_CPU_REQUEST, "memory": STRESS_JOB_MEM_REQUEST},
            ),
        )
    elif len(command) >= 2 and command[0] == "sh" and command[1] == "-lc":
        nb_container = client.V1Container(
            name="nosqlbench",
            image=NOSQLBENCH_IMAGE,
            command=command,
            working_dir=NOSQLBENCH_WORKDIR or None,
            volume_mounts=mounts,
            resources=client.V1ResourceRequirements(
                limits={"cpu": STRESS_JOB_CPU_LIMIT, "memory": STRESS_JOB_MEM_LIMIT},
                requests={"cpu": STRESS_JOB_CPU_REQUEST, "memory": STRESS_JOB_MEM_REQUEST},
            ),
        )
    else:
        nb_container = client.V1Container(
            name="nosqlbench",
            image=NOSQLBENCH_IMAGE,
            command=_nb_java_command_prefix(),
            args=command,
            working_dir=NOSQLBENCH_WORKDIR or None,
            volume_mounts=mounts,
            resources=client.V1ResourceRequirements(
                limits={"cpu": STRESS_JOB_CPU_LIMIT, "memory": STRESS_JOB_MEM_LIMIT},
                requests={"cpu": STRESS_JOB_CPU_REQUEST, "memory": STRESS_JOB_MEM_REQUEST},
            ),
        )
    pod_spec = client.V1PodSpec(
        restart_policy="Never",
        volumes=volumes,
        containers=[nb_container, *( [exporter_container] if exporter_container else [] )],
    )
    nb_labels = {"app": "cassandra-nosqlbench", "managed_by": "chaos-injector", "profile": name}
    return client.V1Job(
        metadata=client.V1ObjectMeta(name=name, namespace=NAMESPACE, labels=nb_labels),
        spec=client.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=STRESS_JOB_TTL_SECONDS_AFTER_FINISHED,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=nb_labels),
                spec=pod_spec,
            ),
        ),
    )


def _nb_cmd_file_workload(
    workload_file: str,
    scenario: str,
    *,
    keyspace: str,
    rf: int,
    main_cycles: int,
    rampup_cycles: int,
    threads: int,
    hosts: str,
    profile_name: str,
    job_name: str,
    job_index: int,
    extra_kv: Optional[List[str]] = None,
) -> List[str]:
    path = os.path.join(NOSQLBENCH_SCENARIO_MOUNT_PATH, workload_file)
    cmd: List[str] = [
        path,
        scenario,
        f"hosts={hosts}",
        f"localdc={CASSANDRA_LOCAL_DC}",
        f"keyspace={keyspace}",
        f"rf={rf}",
        f"main-cycles={main_cycles}",
        f"rampup-cycles={rampup_cycles}",
        f"threads={threads}",
    ]
    if extra_kv:
        cmd.extend(extra_kv)
    cmd.extend(_nb_prometheus_push_args(profile_name, job_name, job_index))
    return cmd


def _start_nb_parallel_jobs(
    params: Dict,
    *,
    profile_name: str,
    build_cmd: Callable[[str, int, str], List[str]],
) -> FaultRecord:
    parallel = _resolve_parallel_jobs(params)
    base = f"nb-{int(time.time())}-{secrets.token_hex(3)}"
    job_names = [f"{base}-{i}" for i in range(parallel)]
    for i, job_name in enumerate(job_names):
        ks = _nb_keyspace_token(job_name)
        cmd = build_cmd(job_name, i, ks)
        batch.create_namespaced_job(namespace=NAMESPACE, body=_build_nosqlbench_job(job_name, cmd))
    logging.info(
        "Started nosqlbench jobs for profile '%s': %s (prom_push=%s)",
        profile_name,
        job_names,
        bool(_nb_prompush_base()),
    )
    return FaultRecord(
        profile=profile_name,
        started_at=time.time(),
        target=_nb_hosts_for_load(),
        params={
            "engine": "nosqlbench",
            "job_names": job_names,
            "job_name": job_names[0],
            "parallel_jobs": parallel,
            "hosts": _nb_hosts_for_load(),
            "local_dc": CASSANDRA_LOCAL_DC,
            "image": NOSQLBENCH_IMAGE,
            "prompush_url_configured": bool(_nb_prompush_base()),
            "request": params,
        },
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _nb_start_baseline_normal(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_BASELINE_THREADS))
    rf = int(params.get("replication_factor", 3))
    hosts = _nb_hosts_for_load()
    read_ratio = int(params.get("read_ratio", 5))
    write_ratio = int(params.get("write_ratio", 5))

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "baseline_normal.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=_nb_rampup_cycles(duration, threads),
            threads=threads,
            hosts=hosts,
            profile_name="baseline-normal",
            job_name=job_name,
            job_index=idx,
            extra_kv=[
                f"read_ratio={read_ratio}",
                f"write_ratio={write_ratio}",
                f"table=nbbase_{idx}",
            ],
        )

    return _start_nb_parallel_jobs(params, profile_name="baseline-normal", build_cmd=build)


def _nb_start_anomaly_hot_partition(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_HOT_THREADS))
    rf = int(params.get("replication_factor", 3))
    hosts = _nb_hosts_for_load()

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "hot_partition.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=_nb_rampup_cycles(duration, threads),
            threads=threads,
            hosts=hosts,
            profile_name="anomaly-hot-partition",
            job_name=job_name,
            job_index=idx,
        )

    return _start_nb_parallel_jobs(params, profile_name="anomaly-hot-partition", build_cmd=build)


def _nb_start_anomaly_compaction_pressure(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_COMPACTION_THREADS))
    pop_end = int(params.get("pop_end", DEFAULT_CASSANDRA_STRESS_POP_BASELINE_END))
    rf = int(params.get("replication_factor", 3))
    hosts = _nb_hosts_for_load()

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "compaction_pressure.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=min(_nb_rampup_cycles(duration, threads), max(5000, pop_end // 100)),
            threads=threads,
            hosts=hosts,
            profile_name="anomaly-compaction-pressure",
            job_name=job_name,
            job_index=idx,
        )

    return _start_nb_parallel_jobs(params, profile_name="anomaly-compaction-pressure", build_cmd=build)


def _nb_start_anomaly_concurrency_spike(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 180))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_SPIKE_THREADS))
    rf = int(params.get("replication_factor", 3))
    hosts = _nb_hosts_for_load()

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "concurrency_spike.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=_nb_rampup_cycles(duration, threads),
            threads=threads,
            hosts=hosts,
            profile_name="anomaly-concurrency-spike",
            job_name=job_name,
            job_index=idx,
        )

    return _start_nb_parallel_jobs(params, profile_name="anomaly-concurrency-spike", build_cmd=build)


def _nb_start_anomaly_mixed_skew_large_payload(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 300))
    threads = int(params.get("threads", DEFAULT_CASSANDRA_STRESS_MIXED_SKEW_THREADS))
    rf = int(params.get("replication_factor", 3))
    hosts = _nb_hosts_for_load()

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "mixed_skew.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=_nb_rampup_cycles(duration, threads),
            threads=threads,
            hosts=hosts,
            profile_name="anomaly-mixed-skew-large-payload",
            job_name=job_name,
            job_index=idx,
        )

    return _start_nb_parallel_jobs(params, profile_name="anomaly-mixed-skew-large-payload", build_cmd=build)


def _nb_start_anomaly_university_memory_pressure(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 120))
    threads = int(params.get("threads", DEFAULT_UNIVERSITY_STRESS_THREADS))
    rf = int(params.get("replication_factor", 3))
    merged = {**params, "parallel_jobs": 1}
    hosts = _university_stress_nodes()

    def build(job_name: str, idx: int, ks: str) -> List[str]:
        return _nb_cmd_file_workload(
            "university_heavy.yaml",
            "default",
            keyspace=ks,
            rf=rf,
            main_cycles=_nb_main_cycles(duration, threads),
            rampup_cycles=_nb_rampup_cycles(duration, threads),
            threads=threads,
            hosts=hosts,
            profile_name="anomaly-university-memory-pressure",
            job_name=job_name,
            job_index=idx,
        )

    return _start_nb_parallel_jobs(merged, profile_name="anomaly-university-memory-pressure", build_cmd=build)


def _nb_start_anomaly_ttl_tombstone(params: Dict) -> FaultRecord:
    write_duration = int(params.get("write_duration_sec", 240))
    read_duration = int(params.get("read_duration_sec", 180))
    write_threads = int(params.get("write_threads", DEFAULT_CASSANDRA_STRESS_TTL_WRITE_THREADS))
    read_threads = int(params.get("read_threads", DEFAULT_CASSANDRA_STRESS_TTL_READ_THREADS))
    ttl_sec = int(params.get("ttl_sec", DEFAULT_CASSANDRA_STRESS_TTL_SEC))
    delay_sec = int(params.get("delay_sec", DEFAULT_CASSANDRA_STRESS_TTL_DELAY_SEC))
    rf = int(params.get("replication_factor", 3))
    merged = {**params, "parallel_jobs": 1}
    base = f"nb-{int(time.time())}-{secrets.token_hex(3)}"
    job_name = f"{base}-0"
    ks = _nb_keyspace_token(job_name)
    hosts = _nb_hosts_for_load()
    w_mc = _nb_main_cycles(write_duration, write_threads)
    w_rc = _nb_rampup_cycles(write_duration, write_threads)
    r_mc = _nb_main_cycles(read_duration, read_threads)

    write_cmd = _nb_cmd_file_workload(
        "ttl_write.yaml",
        "default",
        keyspace=ks,
        rf=rf,
        main_cycles=w_mc,
        rampup_cycles=w_rc,
        threads=write_threads,
        hosts=hosts,
        profile_name="anomaly-ttl-tombstone",
        job_name=job_name,
        job_index=0,
        extra_kv=[f"ttlsec={ttl_sec}"],
    )
    read_cmd = _nb_cmd_file_workload(
        "ttl_read.yaml",
        "default",
        keyspace=ks,
        rf=rf,
        main_cycles=r_mc,
        rampup_cycles=1,
        threads=read_threads,
        hosts=hosts,
        profile_name="anomaly-ttl-tombstone",
        job_name=job_name,
        job_index=0,
    )
    script = (
        _nb_shell_java_invocation(write_cmd)
        + f" && sleep {int(delay_sec)} && "
        + _nb_shell_java_invocation(read_cmd)
    )
    batch.create_namespaced_job(namespace=NAMESPACE, body=_build_nosqlbench_job(job_name, ["sh", "-lc", script]))
    logging.info(
        "Started nosqlbench TTL job '%s' ks=%s (prom_push=%s)",
        job_name,
        ks,
        bool(_nb_prompush_base()),
    )
    return FaultRecord(
        profile="anomaly-ttl-tombstone",
        started_at=time.time(),
        target=hosts,
        params={
            "engine": "nosqlbench",
            "job_names": [job_name],
            "job_name": job_name,
            "parallel_jobs": 1,
            "hosts": hosts,
            "image": NOSQLBENCH_IMAGE,
            "prompush_url_configured": bool(_nb_prompush_base()),
            "request": merged,
        },
        status="running",
        command_start_ts=time.time(),
        verified_start_ts=time.time(),
    )


def _stop_nosqlbench_fault(record: FaultRecord):
    stop = _METRICS_STOP.get(record.profile)
    if stop is not None:
        stop.set()
    engine = (record.params or {}).get("engine")
    if record.profile in {
        "baseline-normal",
        "anomaly-hot-partition",
        "anomaly-compaction-pressure",
        "anomaly-concurrency-spike",
        "anomaly-ttl-tombstone",
        "anomaly-mixed-skew-large-payload",
        "anomaly-university-memory-pressure",
        "short-cpu-spike",
        "cpuhog-like",
        "memleak-like",
    } or engine in ("nosqlbench", "busybox"):
        _delete_stress_jobs(record)
    elif record.profile == "network-congestion-like":
        _delete_network_policy(record.params["network_policy_name"])
    elif record.profile == "bottleneck-like":
        patch = {"spec": {"replicas": record.params["original_replicas"]}}
        apps.patch_namespaced_stateful_set(name="cassandra", namespace=NAMESPACE, body=patch)


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
        # Mixed profiles can hit read-after-write / consistency effects (esp. LOCAL_ONE/RF>1) that trigger
        # validation mismatches during warmup; we still want interval stats for p95/p99.
        "-errors",
        "ignore",
        "-mode",
        "cql3",
        "native",
        "-log",
        # Write interval table to container stdout so Kubernetes log streaming can parse it.
        "interval=1s file=/proc/1/fd/1",
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
            # cassandra-stress expects distribution specs (e.g. FIXED(1)); plain `n=1` fails with
            # "Illegal distribution specification: 1" on cassandra:4.1.
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


def _cmd_anomaly_university_memory_pressure(
    *,
    duration_sec: int,
    threads: int,
    ops: str,
    truncate: str,
) -> list[str]:
    """Wide rows + mixed ops (user YAML) to push heap / memtables / read paths (memory pressure lab)."""
    return [
        CASSANDRA_STRESS_BIN,
        "user",
        "profile=/profiles/university-profile.yaml",
        f"duration={duration_sec}s",
        ops,
        truncate,
        "-node",
        _university_stress_nodes(),
        "-port",
        f"native={CASSANDRA_STRESS_PORT}",
        "-rate",
        f"threads={threads}",
        "-log",
        "interval=1s file=/proc/1/fd/1",
    ]


def _start_cassandra_stress_job(
    params: Dict,
    *,
    profile_name: str,
    command: list[str],
    mount_university_profile: bool = False,
) -> FaultRecord:
    parallel = _resolve_parallel_jobs(params)
    base = f"chaos-{int(time.time())}-{secrets.token_hex(3)}"
    job_names = [f"{base}-{i}" for i in range(parallel)]
    for job_name in job_names:
        batch.create_namespaced_job(
            namespace=NAMESPACE,
            body=_build_cassandra_stress_job(job_name, command, mount_university_profile=mount_university_profile),
        )
    logging.info("Started cassandra-stress jobs for profile '%s': %s", profile_name, job_names)
    # _start_stress_metrics_stream(profile_name, job_names)
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


def _start_anomaly_university_memory_pressure(params: Dict) -> FaultRecord:
    duration = int(params.get("duration_sec", 120))
    threads = int(params.get("threads", DEFAULT_UNIVERSITY_STRESS_THREADS))
    ops = str(params.get("user_ops", DEFAULT_UNIVERSITY_STRESS_OPS)).strip()
    truncate = str(params.get("user_truncate", DEFAULT_UNIVERSITY_TRUNCATE)).strip()
    # Single Job: parallel stress + truncate=once races DDL and keyspace init.
    merged = {**params, "parallel_jobs": 1}
    return _start_cassandra_stress_job(
        merged,
        profile_name="anomaly-university-memory-pressure",
        command=_cmd_anomaly_university_memory_pressure(
            duration_sec=duration,
            threads=threads,
            ops=ops,
            truncate=truncate,
        ),
        mount_university_profile=True,
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
    stop = _METRICS_STOP.get(record.profile)
    if stop is not None:
        stop.set()
    if record.profile in {
        "baseline-normal",
        "anomaly-hot-partition",
        "anomaly-compaction-pressure",
        "anomaly-concurrency-spike",
        "anomaly-ttl-tombstone",
        "anomaly-mixed-skew-large-payload",
        "anomaly-university-memory-pressure",
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
    return jsonify(
        {
            "status": "up",
            "active_fault_count": len(ACTIVE_FAULTS),
            "active_nosqlbench_fault_count": len(ACTIVE_NB_FAULTS),
        }
    )


@app.get("/faults")
def faults():
    return jsonify(
        {
            "active_faults": {k: asdict(v) for k, v in ACTIVE_FAULTS.items()},
            "active_nosqlbench_faults": {k: asdict(v) for k, v in ACTIVE_NB_FAULTS.items()},
        }
    )


VALID_NOSQLBENCH_PROFILES = [
    "baseline-normal",
    "anomaly-hot-partition",
    "anomaly-compaction-pressure",
    "anomaly-concurrency-spike",
    "anomaly-ttl-tombstone",
    "anomaly-mixed-skew-large-payload",
    "anomaly-university-memory-pressure",
    "cpuhog-like",
    "memleak-like",
    "short-cpu-spike",
    "network-congestion-like",
    "bottleneck-like",
]


@app.post("/start_nosqlbench")
def start_nosqlbench():
    """Start load/control faults using NoSQLBench Jobs (Prometheus SLO metrics via PROMPUSH_URL when set)."""
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", "").strip().lower()
    if profile in ACTIVE_NB_FAULTS:
        return jsonify({"error": f"{profile} already active (nosqlbench)"}), 409

    if not _nb_prompush_base():
        logging.warning(
            "PROMPUSH_URL is unset; nosqlbench jobs will run without --report-prompush-to (no client SLO export)."
        )

    try:
        if profile == "baseline-normal":
            record = _nb_start_baseline_normal(body)
        elif profile == "anomaly-hot-partition":
            record = _nb_start_anomaly_hot_partition(body)
        elif profile == "anomaly-compaction-pressure":
            record = _nb_start_anomaly_compaction_pressure(body)
        elif profile == "anomaly-concurrency-spike":
            record = _nb_start_anomaly_concurrency_spike(body)
        elif profile == "anomaly-ttl-tombstone":
            record = _nb_start_anomaly_ttl_tombstone(body)
        elif profile == "anomaly-mixed-skew-large-payload":
            record = _nb_start_anomaly_mixed_skew_large_payload(body)
        elif profile == "anomaly-university-memory-pressure":
            record = _nb_start_anomaly_university_memory_pressure(body)
        elif profile == "cpuhog-like":
            rec = _nb_start_anomaly_concurrency_spike(body)
            rec.profile = "cpuhog-like"
            record = rec
        elif profile == "memleak-like":
            rec = _nb_start_anomaly_compaction_pressure(body)
            rec.profile = "memleak-like"
            record = rec
        elif profile == "short-cpu-spike":
            record = _start_short_cpu_spike(body)
            record.params = {**(record.params or {}), "engine": "busybox", "nosqlbench_api": True}
        elif profile == "network-congestion-like":
            record = _start_network_congestion(body)
            record.params = {**(record.params or {}), "nosqlbench_api": True}
        elif profile == "bottleneck-like":
            record = _start_bottleneck(body)
            record.params = {**(record.params or {}), "nosqlbench_api": True}
        else:
            return (
                jsonify(
                    {
                        "error": "Unknown profile for /start_nosqlbench.",
                        "valid_profiles": VALID_NOSQLBENCH_PROFILES,
                    }
                ),
                400,
            )
    except Exception as ex:
        logging.exception("start_nosqlbench failed for profile=%r body=%s", profile, body)
        return jsonify({"error": str(ex)}), 500

    ACTIVE_NB_FAULTS[profile] = record
    return jsonify({"message": "nosqlbench fault started", "fault": asdict(record)})


@app.post("/stop_nosqlbench")
def stop_nosqlbench():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", "").strip().lower()
    if profile not in ACTIVE_NB_FAULTS:
        return jsonify({"message": "nosqlbench fault not active (already stopped)", "fault": None, "profile": profile})

    record = ACTIVE_NB_FAULTS[profile]
    try:
        _stop_nosqlbench_fault(record)
        record.command_stop_ts = time.time()
        record.verified_stop_ts = time.time()
        record.status = "stopped"
        payload = asdict(record)
        del ACTIVE_NB_FAULTS[profile]
    except Exception as ex:
        logging.exception("stop_nosqlbench failed for profile=%r body=%s record=%s", profile, body, record)
        return jsonify({"error": str(ex)}), 500

    return jsonify({"message": "nosqlbench fault stopped", "fault": payload})


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
        elif profile == "anomaly-university-memory-pressure":
            record = _start_anomaly_university_memory_pressure(body)
        elif profile == "cpuhog-like":
            # Compatibility alias
            record = _start_anomaly_concurrency_spike(body)
            record.profile = "cpuhog-like"
        elif profile == "memleak-like":
            # Compatibility alias
            record = _start_anomaly_compaction_pressure(body)
            record.profile = "memleak-like"
        elif profile == "short-cpu-spike":
            record = _start_short_cpu_spike(body)
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
                            "anomaly-university-memory-pressure",
                            "cpuhog-like",
                            "memleak-like",
                            "network-congestion-like",
                            "bottleneck-like",
                            "short-cpu-spike",
                        ],
                    }
                ),
                400,
            )
    except Exception as ex:
        logging.exception("start_fault failed for profile=%r body=%s", profile, body)
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
        logging.exception("stop_fault failed for profile=%r body=%s record=%s", profile, body, record)
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

    stopped_nb = {}
    for profile in list(ACTIVE_NB_FAULTS.keys()):
        record = ACTIVE_NB_FAULTS[profile]
        try:
            _stop_nosqlbench_fault(record)
            record.command_stop_ts = time.time()
            record.verified_stop_ts = time.time()
            record.status = "stopped"
            stopped_nb[profile] = asdict(record)
            del ACTIVE_NB_FAULTS[profile]
        except Exception as ex:
            stopped_nb[profile] = {"error": str(ex)}

    return jsonify({"message": "reset complete", "stopped": stopped, "stopped_nosqlbench": stopped_nb})


def main():
    _pu = _nb_prompush_base()
    logging.info("chaos-injector starting PROMPUSH_URL=%r prompush_configured=%s", _pu, bool(_pu))
    app.run(host="0.0.0.0", port=8200, threaded=True)


if __name__ == "__main__":
    main()
