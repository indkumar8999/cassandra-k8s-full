import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
from requests import exceptions as req_exc


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class Phase:
    name: str
    duration_sec: int


class ScenarioRunner:
    def __init__(self, args):
        self.args = args
        self.simulator_base = args.simulator_base.rstrip("/")
        self.learner_base = args.learner_base.rstrip("/")
        self.chaos_base = args.chaos_base.rstrip("/")
        self.events: List[Dict] = []
        self.session = requests.Session()

        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.run_started_at = _now()
        self.run_id = args.run_id or f"test5-{int(self.run_started_at)}"
        self.run_dir = self.output_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _record(self, event: str, payload: Optional[Dict] = None):
        item = {"ts": _now(), "ts_iso": _iso(_now()), "event": event, "payload": payload or {}}
        self.events.append(item)
        print(f"[EVENT] {event} {json.dumps(payload or {})}")

    def _request_json(self, method: str, base: str, path: str, body: Optional[Dict] = None, retries: int = 5):
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                if method == "GET":
                    response = self.session.get(f"{base}{path}", timeout=15)
                else:
                    response = self.session.post(f"{base}{path}", json=body or {}, timeout=30)
                response.raise_for_status()
                return response.json()
            except (req_exc.ConnectionError, req_exc.Timeout, req_exc.ChunkedEncodingError) as ex:
                last_error = ex
                if attempt < retries:
                    time.sleep(min(2.0, 0.5 * attempt))
                    continue
                break
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Request failed for {method} {base}{path}")

    def _get(self, base: str, path: str):
        return self._request_json("GET", base, path)

    def _post(self, base: str, path: str, body: Optional[Dict] = None):
        return self._request_json("POST", base, path, body=body)

    def _post_chaos_stop_fault(self, profile: str) -> Dict:
        url = f"{self.chaos_base}/stop_fault"
        response = self.session.post(url, json={"profile": profile}, timeout=30)
        if response.status_code == 404:
            try:
                detail = response.json()
            except Exception:
                detail = {"text": (response.text or "")[:500]}
            return {
                "message": "fault not active at stop (treated as already stopped)",
                "fault": None,
                "profile": profile,
                "chaos_http_status": 404,
                "detail": detail,
            }
        response.raise_for_status()
        return response.json()

    def _sleep_phase(self, phase: Phase):
        self._record("phase_start", {"phase": phase.name, "duration_sec": phase.duration_sec})
        if phase.duration_sec > 0:
            time.sleep(phase.duration_sec)
        self._record("phase_end", {"phase": phase.name})

    def _write_json(self, name: str, payload: Dict):
        out = self.run_dir / name
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _import_som_snapshot(self, snapshot_path: Path) -> Dict:
        if not snapshot_path.is_file():
            raise FileNotFoundError(f"SOM snapshot file not found: {snapshot_path}")
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        resp = self.session.post(f"{self.learner_base}/import/som-snapshot", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def run(self):
        profile = "anomaly-cpu-mixed-cached"

        self._record(
            "run_start",
            {
                "run_id": self.run_id,
                "test": "test_5_cpu_spike_test",
                "fault_profile": profile,
                "load_profile": self.args.load_profile,
                "duration_sec": self.args.cpu_sec,
                "note": "Runs anomaly-cpu-mixed-cached (mixed ratio write=1,read=9) while learner phase is forced to chaos.",
            },
        )

        sim_health = self._get(self.simulator_base, "/health")
        learner_health = self._get(self.learner_base, "/health")
        chaos_health = self._get(self.chaos_base, "/health")
        self._record("health_check", {"simulator": sim_health, "learner": learner_health, "chaos": chaos_health})

        # Keep these consistent with other runners so state is repeatable.
        self._post(self.learner_base, "/reset")
        self._post(self.chaos_base, "/reset_all")
        self._post(self.simulator_base, "/reset-metrics")
        self._post(self.simulator_base, "/resume")

        if self.args.som_snapshot_path:
            import_result = self._import_som_snapshot(Path(self.args.som_snapshot_path))
            self._record("som_snapshot_imported", {"path": self.args.som_snapshot_path, "result": import_result})

        # Force chaos phase even though this is a stress profile.
        self._post(self.simulator_base, "/load", {"profile": self.args.load_profile})
        self._post(self.learner_base, "/phase", {"phase": "chaos"})

        body: Dict = {
            "profile": profile,
            "duration_sec": self.args.cpu_sec,
            "parallel_jobs": self.args.stress_parallel_jobs,
        }
        if self.args.stress_threads is not None:
            body["threads"] = self.args.stress_threads
        if self.args.pop_end is not None:
            body["pop_end"] = self.args.pop_end
        if self.args.replication_factor is not None:
            body["replication_factor"] = self.args.replication_factor

        start_payload = self._post(self.chaos_base, "/start_fault", body)
        self._record("fault_start", start_payload)
        self._sleep_phase(Phase("chaos", self.args.cpu_sec))
        stop_payload = self._post_chaos_stop_fault(profile)
        self._record("fault_stop", stop_payload)

        # Cooldown marker.
        self._post(self.learner_base, "/phase", {"phase": "cooldown"})

        learner_status = self._get(self.learner_base, "/status")
        learner_report = self._get(self.learner_base, "/report")
        score_stream = self._get(self.learner_base, "/score-stream?limit=5000")
        alarms = self._get(self.learner_base, "/alarms?limit=5000")
        simulator_metrics = self._get(self.simulator_base, "/metrics")

        run_finished = _now()
        summary = {
            "run_id": self.run_id,
            "test": "test_5_cpu_spike_test",
            "started_at": self.run_started_at,
            "finished_at": run_finished,
            "duration_sec": round(run_finished - self.run_started_at, 2),
            "fault_profile": profile,
            "load_profile": self.args.load_profile,
            "injection_profile": {
                "target_namespace": self.args.target_namespace,
                "stress_threads": self.args.stress_threads,
                "stress_parallel_jobs": self.args.stress_parallel_jobs,
                "pop_end": self.args.pop_end,
                "replication_factor": self.args.replication_factor,
            },
            "learner_status": learner_status,
            "learner_report": learner_report,
            "simulator_metrics": simulator_metrics,
            "alarm_count": alarms.get("count", 0),
        }

        self._write_json("run_summary.json", summary)
        self._write_json("run_events.json", {"events": self.events})
        self._write_json("learner_report.json", learner_report)
        self._write_json("score_stream.json", score_stream)
        self._write_json("alarms.json", alarms)
        self._write_json("simulator_metrics.json", simulator_metrics)

        self._record("run_complete", {"run_dir": str(self.run_dir), "alarm_count": alarms.get("count", 0)})
        self._write_json("run_events.json", {"events": self.events})


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Test 5: run anomaly-cpu-mixed-cached (mixed ratio write=1,read=9) in chaos mode to bias toward Cassandra CPU."
        )
    )
    parser.add_argument("--simulator-base", default=os.getenv("SIMULATOR_BASE", "http://localhost:8080"))
    parser.add_argument("--learner-base", default=os.getenv("LEARNER_BASE", "http://localhost:8100"))
    parser.add_argument("--chaos-base", default=os.getenv("CHAOS_BASE", "http://localhost:8200"))
    parser.add_argument("--target-namespace", default=os.getenv("TARGET_NAMESPACE", "cassandra-lab"))

    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "cassandra/artifacts"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID"))

    parser.add_argument(
        "--load-profile",
        default=os.getenv("LOAD_PROFILE", "high"),
        help="Simulator load profile during the chaos window.",
    )
    parser.add_argument(
        "--cpu-sec",
        type=int,
        default=int(os.getenv("CPU_SEC", os.getenv("CHAOS_SEC", "180"))),
        help="Duration of the cpu-mixed-cached window (seconds).",
    )

    parser.add_argument("--stress-threads", type=int, default=None)
    parser.add_argument("--pop-end", type=int, default=None)
    parser.add_argument("--replication-factor", type=int, default=None)
    parser.add_argument(
        "--stress-parallel-jobs",
        type=int,
        default=int(os.getenv("STRESS_PARALLEL_JOBS", "8")),
        help="Parallel cassandra-stress Jobs (capped by chaos-injector MAX_STRESS_PARALLEL_JOBS).",
    )

    parser.add_argument(
        "--som-snapshot-path",
        default=os.getenv("SOM_SNAPSHOT_PATH"),
        help=(
            "Path to a trained SOM snapshot JSON (from learner /export/som-snapshot, e.g. som_trained_snapshot.json). "
            "If provided, Test 5 imports it into the learner before running the fault."
        ),
    )
    return parser


def main():
    args = build_parser().parse_args()
    runner = ScenarioRunner(args)
    try:
        runner.run()
    except Exception as ex:
        print(f"[ERROR] test_5_cpu_spike_test failed: {ex}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
