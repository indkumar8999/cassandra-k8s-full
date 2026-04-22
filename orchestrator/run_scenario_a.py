import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
from requests import exceptions as req_exc

from training import bootstrap_train_and_save_som


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
        self.run_id = args.run_id or f"scenario-a-{int(self.run_started_at)}"
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

    def _generate_final_report(self):
        script = Path(__file__).resolve().parent.parent / "reporting" / "generate_report.py"
        if not script.is_file():
            self._record("report_skipped", {"reason": "generate_report.py not found", "path": str(script)})
            print(f"[WARN] Skip report: missing {script}", file=sys.stderr)
            return
        cmd = [
            sys.executable,
            str(script),
            "--run-dir",
            str(self.run_dir.resolve()),
            "--chaos-min-scored",
            str(self.args.report_chaos_min_scored),
            "--max-fp",
            str(self.args.report_max_fp),
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as ex:
            self._record("report_error", {"error": "timeout", "detail": str(ex)})
            print(f"[WARN] Report generation timed out: {ex}", file=sys.stderr)
            return
        if completed.returncode != 0:
            self._record(
                "report_error",
                {
                    "returncode": completed.returncode,
                    "stderr": (completed.stderr or "")[:4000],
                    "stdout": (completed.stdout or "")[:2000],
                },
            )
            print(completed.stderr or completed.stdout or "(no output)", file=sys.stderr)
            return
        tail = (completed.stdout or "").strip()
        if tail:
            print(tail)
        self._record("report_generated", {"run_dir": str(self.run_dir)})

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

    def _stress_burst_body(self) -> Dict:
        """Short, very high cassandra-stress write burst (same chaos profile as test3, different scale)."""
        body: Dict = {
            "profile": "anomaly-concurrency-spike",
            "duration_sec": self.args.short_spike_sec,
            "parallel_jobs": self.args.stress_burst_parallel_jobs,
            "threads": self.args.stress_burst_threads,
        }
        if self.args.stress_burst_pop_end is not None:
            body["pop_end"] = self.args.stress_burst_pop_end
        return body

    def run(self):
        self._record(
            "run_start",
            {
                "run_id": self.run_id,
                "version": "A",
                "tests": [
                    "baseline-normal",
                    "anomaly-concurrency-spike (high write burst)",
                    "anomaly-concurrency-spike",
                ],
            },
        )

        sim_health = self._get(self.simulator_base, "/health")
        learner_health = self._get(self.learner_base, "/health")
        chaos_health = self._get(self.chaos_base, "/health")
        self._record("health_check", {"simulator": sim_health, "learner": learner_health, "chaos": chaos_health})

        self._post(self.learner_base, "/reset")
        self._post(self.chaos_base, "/reset_all")
        self._post(self.simulator_base, "/reset-metrics")
        self._post(self.simulator_base, "/resume")

        bootstrap_train_and_save_som(
            simulator_base=self.simulator_base,
            learner_base=self.learner_base,
            chaos_base=self.chaos_base,
            bootstrap_sim_profile=self.args.bootstrap_sim_profile,
            bootstrap_fault_profile="baseline-normal",
            bootstrap_sec=self.args.bootstrap_sec,
            bootstrap_timeout_sec=self.args.bootstrap_timeout_sec,
            run_dir=self.run_dir,
            post=self._post,
            get=self._get,
            record=self._record,
            post_chaos_stop_fault=self._post_chaos_stop_fault,
            sleep_phase=lambda name, duration: self._sleep_phase(Phase(name, duration)),
        )

        # # Test 1: Normal baseline (no alarms expected).
        # self._post(self.learner_base, "/phase", {"phase": "normal"})
        # baseline_body = {"profile": "baseline-normal", "duration_sec": self.args.baseline_sec}
        # t1_start = self._post(self.chaos_base, "/start_fault", baseline_body)
        # self._record("test1_start", {"profile": "baseline-normal", "start": t1_start})
        # self._sleep_phase(Phase("test1_baseline_normal", self.args.baseline_sec))
        # t1_stop = self._post_chaos_stop_fault("baseline-normal")
        # self._record("test1_stop", {"profile": "baseline-normal", "stop": t1_stop})

        # self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        # self._sleep_phase(Phase("cooldown_after_test1", self.args.cooldown1_sec))

        # # Test 2: Very high cassandra-stress write burst (short window; drives cluster CPU).
        # self._post(self.learner_base, "/phase", {"phase": "chaos"})
        # burst_body = self._stress_burst_body()
        # t2_start = self._post(self.chaos_base, "/start_fault", burst_body)
        # self._record(
        #     "test2_start",
        #     {"profile": "anomaly-concurrency-spike", "variant": "stress_burst", "start": t2_start},
        # )
        # self._sleep_phase(Phase("test2_cassandra_stress_burst", self.args.short_spike_sec))
        # t2_stop = self._post_chaos_stop_fault("anomaly-concurrency-spike")
        # self._record(
        #     "test2_stop",
        #     {"profile": "anomaly-concurrency-spike", "variant": "stress_burst", "stop": t2_stop},
        # )

        # self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        # self._sleep_phase(Phase("cooldown_after_test2", self.args.cooldown2_sec))

        # Test 3: Concurrency spike anomaly (alarms + elastic scale expected).
        self._post(self.simulator_base, "/load", {"profile": self.args.load_profile})
        self._post(self.learner_base, "/phase", {"phase": "chaos"})
        spike_body: Dict = {
            "profile": "anomaly-concurrency-spike",
            "duration_sec": self.args.concurrency_sec,
            "cpu_workers": self.args.cpu_workers,
            "mem_mb": self.args.mem_mb,
            "replicas": self.args.bottleneck_replicas,
        }
        if self.args.stress_threads is not None:
            spike_body["threads"] = self.args.stress_threads
        if self.args.stress_pop_end is not None:
            spike_body["pop_end"] = self.args.stress_pop_end
        spike_body["parallel_jobs"] = self.args.stress_parallel_jobs
        spike_start = self._post(self.chaos_base, "/start_fault", spike_body)
        self._record("test3_start", {"profile": "anomaly-concurrency-spike", "start": spike_start})
        # Compatibility with reporting: chaos window = last fault_start/fault_stop.
        self._record("fault_start", spike_start)
        self._sleep_phase(Phase("test3_anomaly_concurrency_spike", self.args.concurrency_sec))
        spike_stop = self._post_chaos_stop_fault("anomaly-concurrency-spike")
        self._record("test3_stop", {"profile": "anomaly-concurrency-spike", "stop": spike_stop})
        self._record("fault_stop", spike_stop)

        self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        self._post(self.simulator_base, "/load", {"profile": self.args.cooldown_sim_profile})
        self._sleep_phase(Phase("cooldown_after_test3", self.args.cooldown3_sec))

        learner_status = self._get(self.learner_base, "/status")
        learner_report = self._get(self.learner_base, "/report")
        score_stream = self._get(self.learner_base, "/score-stream?limit=5000")
        alarms = self._get(self.learner_base, "/alarms?limit=5000")
        simulator_metrics = self._get(self.simulator_base, "/metrics")

        som_snapshot: Dict = {}
        try:
            som_snapshot = self._get(self.learner_base, "/export/som-snapshot")
        except Exception as ex:
            som_snapshot = {"error": str(ex), "note": "Deploy ubl-learner with /export/som-snapshot or check learner logs."}

        run_finished = _now()
        summary = {
            "run_id": self.run_id,
            "version": "A",
            "started_at": self.run_started_at,
            "finished_at": run_finished,
            "duration_sec": round(run_finished - self.run_started_at, 2),
            "bootstrap_fault_profile": "baseline-normal",
            "tests": [
                {"name": "test1", "profile": "baseline-normal", "duration_sec": self.args.baseline_sec},
                {
                    "name": "test2",
                    "profile": "anomaly-concurrency-spike",
                    "variant": "stress_burst",
                    "duration_sec": self.args.short_spike_sec,
                    "threads": self.args.stress_burst_threads,
                    "parallel_jobs": self.args.stress_burst_parallel_jobs,
                    "pop_end": self.args.stress_burst_pop_end,
                },
                {"name": "test3", "profile": "anomaly-concurrency-spike", "duration_sec": self.args.concurrency_sec},
            ],
            "phase_durations": {
                "bootstrap_sec": self.args.bootstrap_sec,
                "cooldown_after_test1_sec": self.args.cooldown1_sec,
                "cooldown_after_test2_sec": self.args.cooldown2_sec,
                "cooldown_after_test3_sec": self.args.cooldown3_sec,
            },
            "injection_profile": {
                "target_namespace": self.args.target_namespace,
                "cpu_workers": self.args.cpu_workers,
                "mem_mb": self.args.mem_mb,
                "bottleneck_replicas": self.args.bottleneck_replicas,
                "stress_burst_threads": self.args.stress_burst_threads,
                "stress_burst_parallel_jobs": self.args.stress_burst_parallel_jobs,
                "stress_burst_pop_end": self.args.stress_burst_pop_end,
                "stress_threads": self.args.stress_threads,
                "stress_pop_end": self.args.stress_pop_end,
                "stress_parallel_jobs": self.args.stress_parallel_jobs,
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
        self._write_json("som_snapshot.json", som_snapshot)

        if not self.args.skip_report:
            self._generate_final_report()

        self._record("run_complete", {"run_dir": str(self.run_dir), "alarm_count": alarms.get("count", 0)})
        self._write_json("run_events.json", {"events": self.events})


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Scenario A: bootstrap, then baseline-normal → cooldown → "
            "high cassandra-stress write burst → cooldown → anomaly-concurrency-spike → cooldown."
        )
    )
    parser.add_argument("--simulator-base", default=os.getenv("SIMULATOR_BASE", "http://localhost:8080"))
    parser.add_argument("--learner-base", default=os.getenv("LEARNER_BASE", "http://localhost:8100"))
    parser.add_argument("--chaos-base", default=os.getenv("CHAOS_BASE", "http://localhost:8200"))
    parser.add_argument("--target-namespace", default=os.getenv("TARGET_NAMESPACE", "cassandra-lab"))
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "cassandra/artifacts"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID"))

    # Simulator load profiles (match run_scenario.py defaults)
    parser.add_argument(
        "--bootstrap-sim-profile",
        default=os.getenv("BOOTSTRAP_SIM_PROFILE", "low"),
        help="Simulator load profile during bootstrap + early tests.",
    )
    parser.add_argument(
        "--load-profile",
        default=os.getenv("LOAD_PROFILE", "high"),
        help="Simulator load profile before the concurrency spike test.",
    )
    parser.add_argument(
        "--cooldown-sim-profile",
        default=os.getenv("COOLDOWN_SIM_PROFILE", "medium"),
        help="Simulator load profile during the final cooldown window.",
    )

    # Fixed plan defaults (per your demo plan)
    parser.add_argument("--bootstrap-sec", type=int, default=int(os.getenv("BOOTSTRAP_SEC", "180")))
    parser.add_argument(
        "--bootstrap-timeout-sec",
        type=int,
        default=int(os.getenv("BOOTSTRAP_TIMEOUT_SEC", "1800")),
        help="Max time to wait for learner to report ready after bootstrap (default 1800s).",
    )
    parser.add_argument("--baseline-sec", type=int, default=int(os.getenv("BASELINE_SEC", "120")))
    parser.add_argument(
        "--short-spike-sec",
        type=int,
        default=int(os.getenv("SHORT_SPIKE_SEC", "2")),
        help="Duration of the high cassandra-stress burst (test2), default 2s.",
    )
    parser.add_argument(
        "--stress-burst-threads",
        type=int,
        default=int(os.getenv("STRESS_BURST_THREADS", "10000")),
        help="cassandra-stress threads= for the short write burst (test2).",
    )
    parser.add_argument(
        "--stress-burst-parallel-jobs",
        type=int,
        default=int(os.getenv("STRESS_BURST_PARALLEL_JOBS", "8")),
        help="Parallel stress Jobs for test2 (capped by chaos-injector MAX_STRESS_PARALLEL_JOBS).",
    )
    parser.add_argument(
        "--stress-burst-pop-end",
        type=int,
        default=None,
        help="Optional -pop seq=1..N end for test2 (chaos-injector default if omitted).",
    )
    parser.add_argument("--cooldown1-sec", type=int, default=int(os.getenv("COOLDOWN1_SEC", "75")))
    parser.add_argument("--cooldown2-sec", type=int, default=int(os.getenv("COOLDOWN2_SEC", "75")))
    parser.add_argument("--concurrency-sec", type=int, default=int(os.getenv("CONCURRENCY_SEC", "120")))
    parser.add_argument("--cooldown3-sec", type=int, default=int(os.getenv("COOLDOWN3_SEC", "120")))

    # Match run_scenario.py anomaly payload knobs
    parser.add_argument("--cpu-workers", type=int, default=int(os.getenv("CHAOS_CPU_WORKERS", "2")))
    parser.add_argument("--mem-mb", type=int, default=int(os.getenv("CHAOS_MEM_MB", "1024")))
    parser.add_argument("--bottleneck-replicas", type=int, default=int(os.getenv("CHAOS_BOTTLENECK_REPLICAS", "2")))
    parser.add_argument("--stress-threads", type=int, default=None)
    parser.add_argument("--stress-pop-end", type=int, default=None)
    parser.add_argument(
        "--stress-parallel-jobs",
        type=int,
        default=int(os.getenv("STRESS_PARALLEL_JOBS", "8")),
        help="Parallel cassandra-stress Jobs for the concurrency spike test (default 8 for demo visibility).",
    )

    parser.add_argument("--skip-report", action="store_true", help="Do not run reporting/generate_report.py after the run.")
    parser.add_argument("--report-chaos-min-scored", type=int, default=int(os.getenv("REPORT_CHAOS_MIN_SCORED", "50")))
    parser.add_argument("--report-max-fp", type=int, default=int(os.getenv("REPORT_MAX_FP", "10")))
    return parser


def main():
    args = build_parser().parse_args()
    runner = ScenarioRunner(args)
    runner.run()


if __name__ == "__main__":
    main()

