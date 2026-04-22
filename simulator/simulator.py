import os
import time
import uuid
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean
from typing import Optional

from flask import Flask, request, jsonify
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy
from cassandra import ConsistencyLevel


CONTACT_POINTS = os.getenv(
    "CONTACT_POINTS",
    "cassandra-0.cassandra.cassandra-lab.svc.cluster.local,cassandra-1.cassandra.cassandra-lab.svc.cluster.local,cassandra-2.cassandra.cassandra-lab.svc.cluster.local"
).split(",")

CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
KEYSPACE = os.getenv("KEYSPACE", "loadtest")
TABLE_NAME = os.getenv("TABLE_NAME", "events")
DURATION_SEC = int(os.getenv("DURATION_SEC", "3600"))
CONSISTENCY_NAME = os.getenv("CONSISTENCY", "LOCAL_QUORUM").upper()
REPLICATION_FACTOR = int(os.getenv("REPLICATION_FACTOR", "3"))

PROFILE_CONFIG = {
    "low": {
        "workers": 10,
        "ops_per_sec": 50,
        "write_ratio": 0.7
    },
    "medium": {
        "workers": 30,
        "ops_per_sec": 200,
        "write_ratio": 0.7
    },
    "high": {
        "workers": 80,
        "ops_per_sec": 800,
        "write_ratio": 0.7
    }
}

app = Flask(__name__)

stats_lock = threading.Lock()
control_lock = threading.Lock()

write_latencies = []
read_latencies = []
write_success = 0
read_success = 0
write_failures = 0
read_failures = 0
inserted_ids = []

current_profile = "medium"
current_config = PROFILE_CONFIG["medium"].copy()
running = True
stop_requested = False

session = None
cluster = None
insert_stmt = None
select_stmt = None


def get_consistency(name: str):
    mapping = {
        "ONE": ConsistencyLevel.ONE,
        "QUORUM": ConsistencyLevel.QUORUM,
        "LOCAL_QUORUM": ConsistencyLevel.LOCAL_QUORUM,
        "ALL": ConsistencyLevel.ALL
    }
    return mapping.get(name, ConsistencyLevel.LOCAL_QUORUM)


CONSISTENCY = get_consistency(CONSISTENCY_NAME)


@app.get("/health")
def health():
    return jsonify({
        "status": "up",
        "running": running,
        "profile": current_profile
    })


@app.get("/load")
def get_load():
    with control_lock:
        return jsonify({
            "profile": current_profile,
            "config": current_config,
            "running": running,
            "stop_requested": stop_requested
        })


@app.post("/load")
def set_load():
    global current_profile, current_config

    body = request.get_json(silent=True) or {}

    with control_lock:
        if "profile" in body:
            profile = str(body["profile"]).lower()
            if profile not in PROFILE_CONFIG:
                return jsonify({
                    "error": f"invalid profile '{profile}'. valid profiles: {list(PROFILE_CONFIG.keys())}"
                }), 400
            current_profile = profile
            current_config = PROFILE_CONFIG[profile].copy()

        if "workers" in body:
            current_config["workers"] = max(1, int(body["workers"]))

        if "ops_per_sec" in body:
            current_config["ops_per_sec"] = max(1, int(body["ops_per_sec"]))

        if "write_ratio" in body:
            write_ratio = float(body["write_ratio"])
            if write_ratio < 0 or write_ratio > 1:
                return jsonify({"error": "write_ratio must be between 0 and 1"}), 400
            current_config["write_ratio"] = write_ratio

        response = {
            "message": "load updated",
            "profile": current_profile,
            "config": current_config
        }

    return jsonify(response)


@app.post("/pause")
def pause():
    global running
    with control_lock:
        running = False
    return jsonify({"message": "simulator paused"})


@app.post("/resume")
def resume():
    global running
    with control_lock:
        running = True
    return jsonify({"message": "simulator resumed"})


@app.post("/stop")
def stop():
    global stop_requested
    with control_lock:
        stop_requested = True
    return jsonify({"message": "simulator stop requested"})


@app.post("/reset-metrics")
def reset_metrics():
    global write_success, read_success, write_failures, read_failures

    with stats_lock:
        write_latencies.clear()
        read_latencies.clear()
        inserted_ids.clear()
        write_success = 0
        read_success = 0
        write_failures = 0
        read_failures = 0

    return jsonify({"message": "metrics reset"})


@app.get("/metrics")
def metrics():
    with stats_lock:
        avg_write = mean(write_latencies) if write_latencies else 0
        avg_read = mean(read_latencies) if read_latencies else 0
        p95_write = percentile(write_latencies, 95)
        p95_read = percentile(read_latencies, 95)

        data = {
            "writes": {
                "success": write_success,
                "failures": write_failures,
                "avg_latency_ms": round(avg_write, 2),
                "p95_latency_ms": round(p95_write, 2)
            },
            "reads": {
                "success": read_success,
                "failures": read_failures,
                "avg_latency_ms": round(avg_read, 2),
                "p95_latency_ms": round(p95_read, 2)
            },
            "inserted_ids_count": len(inserted_ids)
        }

    with control_lock:
        data["profile"] = current_profile
        data["config"] = current_config
        data["running"] = running
        data["stop_requested"] = stop_requested

    return jsonify(data)


@app.get("/metrics/prometheus")
def metrics_prometheus():
    snapshot = snapshot_metrics()
    registry = CollectorRegistry()

    gauge_writes_success = Gauge("simulator_writes_success_total", "Successful write count", registry=registry)
    gauge_writes_failures = Gauge("simulator_writes_failures_total", "Failed write count", registry=registry)
    gauge_reads_success = Gauge("simulator_reads_success_total", "Successful read count", registry=registry)
    gauge_reads_failures = Gauge("simulator_reads_failures_total", "Failed read count", registry=registry)
    gauge_avg_write = Gauge("simulator_write_latency_avg_ms", "Average write latency in ms", registry=registry)
    gauge_p95_write = Gauge("simulator_write_latency_p95_ms", "P95 write latency in ms", registry=registry)
    gauge_avg_read = Gauge("simulator_read_latency_avg_ms", "Average read latency in ms", registry=registry)
    gauge_p95_read = Gauge("simulator_read_latency_p95_ms", "P95 read latency in ms", registry=registry)
    gauge_inserted_ids = Gauge("simulator_inserted_ids_count", "Tracked inserted IDs", registry=registry)
    gauge_running = Gauge("simulator_running", "Simulator run state (1 running, 0 paused)", registry=registry)
    gauge_stop_requested = Gauge("simulator_stop_requested", "Stop requested flag (1/0)", registry=registry)
    gauge_workers = Gauge("simulator_config_workers", "Configured worker threads", registry=registry)
    gauge_ops = Gauge("simulator_config_ops_per_sec", "Configured operations per second", registry=registry)
    gauge_write_ratio = Gauge("simulator_config_write_ratio", "Configured write ratio", registry=registry)
    gauge_profile = Gauge(
        "simulator_profile_state",
        "Current load profile as one-hot gauge",
        labelnames=["profile"],
        registry=registry
    )

    with control_lock:
        profile = current_profile
        config = current_config.copy()
        is_running = running
        stop_flag = stop_requested

    gauge_writes_success.set(snapshot["write_success"])
    gauge_writes_failures.set(snapshot["write_failures"])
    gauge_reads_success.set(snapshot["read_success"])
    gauge_reads_failures.set(snapshot["read_failures"])
    gauge_avg_write.set(snapshot["avg_write_ms"])
    gauge_p95_write.set(snapshot["p95_write_ms"])
    gauge_avg_read.set(snapshot["avg_read_ms"])
    gauge_p95_read.set(snapshot["p95_read_ms"])
    gauge_inserted_ids.set(len(inserted_ids))
    gauge_running.set(1 if is_running else 0)
    gauge_stop_requested.set(1 if stop_flag else 0)
    gauge_workers.set(config["workers"])
    gauge_ops.set(config["ops_per_sec"])
    gauge_write_ratio.set(config["write_ratio"])

    for known_profile in PROFILE_CONFIG:
        gauge_profile.labels(profile=known_profile).set(1 if profile == known_profile else 0)

    return generate_latest(registry), 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}


def percentile(values, pct):
    if not values:
        return 0
    sorted_vals = sorted(values)
    index = max(0, min(len(sorted_vals) - 1, int((pct / 100.0) * len(sorted_vals)) - 1))
    return sorted_vals[index]


def wait_for_query_readiness(session_obj, retries=30, delay=5):
    for attempt in range(1, retries + 1):
        try:
            session_obj.execute("SELECT now() FROM system.local")
            print(f"[INFO] Cassandra query readiness confirmed on attempt {attempt}")
            return
        except Exception as ex:
            print(f"[WARN] Cassandra not query-ready yet ({attempt}/{retries}): {ex}")
            time.sleep(delay)

    raise RuntimeError("Cassandra session connected, but queries never became ready")


def create_schema(session_obj):
    session_obj.execute(f"""
        CREATE KEYSPACE IF NOT EXISTS {KEYSPACE}
        WITH replication = {{
            'class': 'SimpleStrategy',
            'replication_factor': {REPLICATION_FACTOR}
        }}
    """)

    session_obj.set_keyspace(KEYSPACE)

    session_obj.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            event_id UUID PRIMARY KEY,
            device_id TEXT,
            metric_type TEXT,
            metric_value DOUBLE,
            created_at TIMESTAMP
        )
    """)

    print(f"[INFO] Schema ready: {KEYSPACE}.{TABLE_NAME}")


def prepare_statements(session_obj):
    prepared_insert = session_obj.prepare(f"""
        INSERT INTO {KEYSPACE}.{TABLE_NAME}
        (event_id, device_id, metric_type, metric_value, created_at)
        VALUES (?, ?, ?, ?, ?)
    """)
    prepared_insert.consistency_level = CONSISTENCY

    prepared_select = session_obj.prepare(f"""
        SELECT event_id, device_id, metric_type, metric_value, created_at
        FROM {KEYSPACE}.{TABLE_NAME}
        WHERE event_id = ?
    """)
    prepared_select.consistency_level = CONSISTENCY

    return prepared_insert, prepared_select


def init_cassandra():
    global session, cluster, insert_stmt, select_stmt

    load_balancing_policy = TokenAwarePolicy(
        DCAwareRoundRobinPolicy(local_dc="DC1")
    )

    cluster = Cluster(
        contact_points=CONTACT_POINTS,
        port=CASSANDRA_PORT,
        load_balancing_policy=load_balancing_policy
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, 31):
        try:
            print(f"[INFO] Attempting Cassandra connection {attempt}/30")
            session = cluster.connect()
            print("[INFO] Connected to Cassandra control connection")
            break
        except Exception as ex:
            last_error = ex
            print(f"[WARN] Cassandra connection attempt failed: {ex}")
            time.sleep(10)
    else:
        raise RuntimeError(f"Could not connect to Cassandra after retries: {last_error}")

    wait_for_query_readiness(session)
    create_schema(session)
    insert_stmt, select_stmt = prepare_statements(session)


def record_latency(bucket, value):
    with stats_lock:
        bucket.append(value)


def do_write():
    global write_success, write_failures

    event_id = uuid.uuid4()
    payload = (
        event_id,
        f"device-{random.randint(1, 5000)}",
        random.choice(["cpu", "mem", "disk", "net"]),
        round(random.uniform(0, 100), 2),
        int(time.time() * 1000)
    )

    start = time.perf_counter()

    try:
        session.execute(insert_stmt, payload)
        elapsed_ms = (time.perf_counter() - start) * 1000

        with stats_lock:
            inserted_ids.append(event_id)
            write_success += 1

        record_latency(write_latencies, elapsed_ms)
    except Exception as ex:
        print(f"[WRITE ERROR] {ex}")
        with stats_lock:
            write_failures += 1


def do_read():
    global read_success, read_failures

    with stats_lock:
        if not inserted_ids:
            return
        event_id = random.choice(inserted_ids)

    start = time.perf_counter()

    try:
        result = session.execute(select_stmt, (event_id,))
        _ = list(result)
        elapsed_ms = (time.perf_counter() - start) * 1000

        with stats_lock:
            read_success += 1

        record_latency(read_latencies, elapsed_ms)
    except Exception as ex:
        print(f"[READ ERROR] {ex}")
        with stats_lock:
            read_failures += 1


def snapshot_metrics():
    with stats_lock:
        total_writes = write_success + write_failures
        total_reads = read_success + read_failures
        total_ops = total_writes + total_reads

        avg_write = mean(write_latencies) if write_latencies else 0
        avg_read = mean(read_latencies) if read_latencies else 0
        p95_write = percentile(write_latencies, 95)
        p95_read = percentile(read_latencies, 95)

        return {
            "total_ops": total_ops,
            "total_writes": total_writes,
            "total_reads": total_reads,
            "write_success": write_success,
            "read_success": read_success,
            "write_failures": write_failures,
            "read_failures": read_failures,
            "avg_write_ms": avg_write,
            "avg_read_ms": avg_read,
            "p95_write_ms": p95_write,
            "p95_read_ms": p95_read
        }


def print_metrics(start_time):
    elapsed = max(time.time() - start_time, 1)
    stats = snapshot_metrics()

    with control_lock:
        profile = current_profile
        cfg = current_config.copy()
        is_running = running

    print(
        f"[METRICS] elapsed={elapsed:.1f}s "
        f"running={is_running} "
        f"profile={profile} "
        f"workers={cfg['workers']} "
        f"ops_per_sec={cfg['ops_per_sec']} "
        f"write_ratio={cfg['write_ratio']} "
        f"ops={stats['total_ops']} "
        f"ops/sec={stats['total_ops']/elapsed:.2f} "
        f"writes={stats['write_success']}/{stats['total_writes']} "
        f"reads={stats['read_success']}/{stats['total_reads']} "
        f"avg_write_ms={stats['avg_write_ms']:.2f} "
        f"p95_write_ms={stats['p95_write_ms']:.2f} "
        f"avg_read_ms={stats['avg_read_ms']:.2f} "
        f"p95_read_ms={stats['p95_read_ms']:.2f} "
        f"write_failures={stats['write_failures']} "
        f"read_failures={stats['read_failures']}"
    )


def run_load_loop():
    start_time = time.time()
    next_metrics_time = start_time + 10

    while True:
        with control_lock:
            if stop_requested:
                print("[INFO] Stop requested. Exiting load loop.")
                break

            is_running = running
            cfg = current_config.copy()

        if DURATION_SEC > 0 and (time.time() - start_time >= DURATION_SEC):
            print("[INFO] Duration reached. Stopping load loop.")
            break

        if not is_running:
            time.sleep(1)
            continue

        workers = cfg["workers"]
        ops_per_sec = cfg["ops_per_sec"]
        write_ratio = cfg["write_ratio"]

        batch_start = time.time()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []

            for _ in range(ops_per_sec):
                if random.random() < write_ratio:
                    futures.append(executor.submit(do_write))
                else:
                    futures.append(executor.submit(do_read))

            for future in as_completed(futures):
                future.result()

        now = time.time()

        if now >= next_metrics_time:
            print_metrics(start_time)
            next_metrics_time = now + 10

        elapsed_batch = now - batch_start
        if elapsed_batch < 1.0:
            time.sleep(1.0 - elapsed_batch)

    print("[INFO] Load loop finished")
    print_metrics(start_time)


def start_flask():
    app.run(host="0.0.0.0", port=8080, threaded=True)


def main():
    try:
        init_cassandra()

        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        run_load_loop()
    finally:
        if cluster is not None:
            try:
                cluster.shutdown()
            except Exception as ex:
                print(f"[WARN] Error during cluster shutdown: {ex}")


if __name__ == "__main__":
    main()
