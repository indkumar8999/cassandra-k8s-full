"""
End-to-end lab scenario using chaos-injector NoSQLBench APIs (/start_nosqlbench, /stop_nosqlbench).

Mirrors orchestrator/run_scenario.py but drives NB5 Jobs + optional Prometheus push (PROMPUSH_URL on chaos-injector).

Default timings: 15s normal baseline (NoSQLBench baseline-normal hold after learner ready), then 60s anomaly phase.
"""
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


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class Phase:
    name: str
    duration_sec: int


class NoSQLBenchScenarioRunner:
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
        self.run_id = args.run_id or f"scenario-nb-{int(self.run_started_at)}"
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

    def _post_chaos_stop_nosqlbench(self, profile: str) -> Dict:
        """POST chaos /stop_nosqlbench; tolerate 404 like /stop_fault."""
        url = f"{self.chaos_base}/stop_nosqlbench"
        response = self.session.post(url, json={"profile": profile}, timeout=30)
        if response.status_code == 404:
            try:
                detail = response.json()
            except Exception:
                detail = {"text": (response.text or "")[:500]}
            return {
                "message": "nosqlbench fault not active at stop (treated as already stopped)",
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

    def _wait_learner_ready(self, timeout_sec: int):
        started = _now()
        last_error = None
        last_status: Optional[Dict] = None
        while _now() - started < timeout_sec:
            try:
                status = self._get(self.learner_base, "/status")
                last_status = status
                if status.get("ready"):
                    self._record("learner_ready", status)
                    return
            except (req_exc.ConnectionError, req_exc.Timeout, req_exc.ChunkedEncodingError) as ex:
                last_error = str(ex)
            time.sleep(2)
        detail = ""
        if last_status is not None:
            detail = (
                f" Last /status: trained={last_status.get('trained')} "
                f"bootstrap_valid={last_status.get('bootstrap_valid_samples')}/"
                f"{last_status.get('bootstrap_target_samples')} "
                f"dropped_tier_a={last_status.get('total_samples_dropped_missing_tier_a')} "
                f"last_error={last_status.get('last_error')!r}."
            )
        if last_error:
            raise TimeoutError(
                f"Learner did not become ready before timeout. Last connection error: {last_error}.{detail}"
            )
        raise TimeoutError(f"Learner did not become ready before timeout.{detail}")

    def _write_json(self, name: str, payload: Dict):
        out = self.run_dir / name
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def run(self):
        self._record(
            "run_start",
            {
                "run_id": self.run_id,
                "chaos_api": "nosqlbench",
                "load_profile": self.args.load_profile,
                "fault_profile": self.args.fault_profile,
                "bootstrap_fault_profile": self.args.bootstrap_fault_profile,
                "start_fault_profile": self.args.start_fault_profile,
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

        self._post(self.simulator_base, "/load", {"profile": self.args.bootstrap_sim_profile})
        self._post(self.learner_base, "/phase", {"phase": "normal"})

        baseline_dur = self.args.bootstrap_fault_duration_sec
        if baseline_dur <= 0:
            baseline_dur = min(
                max(self.args.bootstrap_timeout_sec + 600, 1200),
                7200,
            )
        baseline_body: Dict = {
            "profile": self.args.bootstrap_fault_profile,
            "duration_sec": baseline_dur,
            "cpu_workers": self.args.cpu_workers,
            "mem_mb": self.args.mem_mb,
            "replicas": self.args.bottleneck_replicas,
        }
        if self.args.bootstrap_nb_threads is not None:
            baseline_body["threads"] = self.args.bootstrap_nb_threads
        if self.args.bootstrap_nb_pop_end is not None:
            baseline_body["pop_end"] = self.args.bootstrap_nb_pop_end
        baseline_body["parallel_jobs"] = self.args.bootstrap_nb_parallel_jobs
        baseline_start = self._post(self.chaos_base, "/start_nosqlbench", baseline_body)
        self._record("baseline_nosqlbench_fault_start", baseline_start)

        self._record(
            "bootstrap_wait_start",
            {
                "timeout_sec": self.args.bootstrap_timeout_sec,
                "bootstrap_fault_profile": self.args.bootstrap_fault_profile,
                "bootstrap_fault_duration_sec": baseline_dur,
                "simulator_profile_during_bootstrap": self.args.bootstrap_sim_profile,
                "learner_phase": "normal",
            },
        )
        self._wait_learner_ready(self.args.bootstrap_timeout_sec)
        self._record("bootstrap_wait_end", {})

        # With a pretrained learner, /status becomes ready immediately; without a hold, baseline NB would be
        # stopped almost instantly. When bootstrap fault duration is explicit (>0), hold that many seconds here.
        if self.args.bootstrap_fault_duration_sec > 0:
            self._sleep_phase(Phase("baseline_hold", self.args.bootstrap_fault_duration_sec))

        baseline_stop = self._post_chaos_stop_nosqlbench(self.args.bootstrap_fault_profile)
        self._record("baseline_nosqlbench_fault_stop", baseline_stop)

        self._post(self.simulator_base, "/load", {"profile": self.args.load_profile})
        self._post(self.learner_base, "/phase", {"phase": "chaos"})

        # Optional non-NoSQLBench fault injection (e.g. short-cpu-spike) before starting the anomaly NB job(s).
        if self.args.start_fault_profile:
            start_fault_body: Dict = {
                "profile": self.args.start_fault_profile,
                "duration_sec": self.args.start_fault_duration_sec,
                "target_mode": self.args.start_fault_target_mode,
            }
            if self.args.start_fault_target_pod:
                start_fault_body["target_pod"] = self.args.start_fault_target_pod
            self._record("start_fault_start", start_fault_body)
            start_fault_resp = self._post(self.chaos_base, "/start_fault", start_fault_body)
            self._record("start_fault_end", start_fault_resp)

        fault_body: Dict = {
            "profile": self.args.fault_profile,
            "duration_sec": self.args.chaos_sec,
            "cpu_workers": self.args.cpu_workers,
            "mem_mb": self.args.mem_mb,
            "replicas": self.args.bottleneck_replicas,
        }
        if self.args.nb_threads is not None:
            fault_body["threads"] = self.args.nb_threads
        if self.args.nb_pop_end is not None:
            fault_body["pop_end"] = self.args.nb_pop_end
        fault_body["parallel_jobs"] = self.args.nb_parallel_jobs
        fault_start_payload = self._post(self.chaos_base, "/start_nosqlbench", fault_body)
        self._record("fault_nosqlbench_start", fault_start_payload)
        self._sleep_phase(Phase("chaos", self.args.chaos_sec))
        fault_stop_payload = self._post_chaos_stop_nosqlbench(self.args.fault_profile)
        self._record("fault_nosqlbench_stop", fault_stop_payload)

        self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        self._post(self.simulator_base, "/load", {"profile": "medium"})
        self._sleep_phase(Phase("cooldown", self.args.cooldown_sec))

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
            "chaos_api": "nosqlbench",
            "started_at": self.run_started_at,
            "finished_at": run_finished,
            "duration_sec": round(run_finished - self.run_started_at, 2),
            "fault_profile": self.args.fault_profile,
            "load_profile": self.args.load_profile,
            "bootstrap_fault_profile": self.args.bootstrap_fault_profile,
            "phase_durations": {
                "bootstrap_sim_profile": self.args.bootstrap_sim_profile,
                "chaos_sec": self.args.chaos_sec,
                "cooldown_sec": self.args.cooldown_sec,
                "load_sec_deprecated": self.args.load_sec,
                "normal_sec_deprecated": self.args.normal_sec,
            },
            "injection_profile": {
                "bootstrap_fault_profile": self.args.bootstrap_fault_profile,
                "fault_profile": self.args.fault_profile,
                "target_namespace": self.args.target_namespace,
                "cpu_workers": self.args.cpu_workers,
                "mem_mb": self.args.mem_mb,
                "bottleneck_replicas": self.args.bottleneck_replicas,
                "bootstrap_nb_threads": self.args.bootstrap_nb_threads,
                "bootstrap_nb_pop_end": self.args.bootstrap_nb_pop_end,
                "nb_threads": self.args.nb_threads,
                "nb_pop_end": self.args.nb_pop_end,
                "bootstrap_nb_parallel_jobs": self.args.bootstrap_nb_parallel_jobs,
                "nb_parallel_jobs": self.args.nb_parallel_jobs,
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
            "Runs baseline NoSQLBench load (/start_nosqlbench) during normal phase, then anomaly profile; "
            "then cooldown. Default: 15s baseline hold, 60s chaos. "
            "Configure chaos-injector PROMPUSH_URL (default victoria:plain:…→VictoriaMetrics for NB metrics)."
        )
    )
    parser.add_argument("--simulator-base", default=os.getenv("SIMULATOR_BASE", "http://localhost:8080"))
    parser.add_argument("--learner-base", default=os.getenv("LEARNER_BASE", "http://localhost:8100"))
    parser.add_argument("--chaos-base", default=os.getenv("CHAOS_BASE", "http://localhost:8200"))
    parser.add_argument("--target-namespace", default=os.getenv("TARGET_NAMESPACE", "cassandra-lab"))
    parser.add_argument(
        "--bootstrap-fault-profile",
        default=os.getenv("BOOTSTRAP_FAULT_PROFILE", "baseline-normal"),
        help="Chaos profile during SOM bootstrap (NoSQLBench), e.g. baseline-normal.",
    )
    parser.add_argument(
        "--bootstrap-sim-profile",
        default=os.getenv("BOOTSTRAP_SIM_PROFILE", "low"),
        help="Simulator load profile while bootstrap fault runs (low recommended to isolate baseline stress).",
    )
    parser.add_argument(
        "--bootstrap-fault-duration-sec",
        type=int,
        default=int(os.getenv("BOOTSTRAP_FAULT_DURATION_SEC", "15")),
        help=(
            "Baseline NoSQLBench job duration_sec and wall-clock hold after learner ready before stop; "
            "0 = auto job duration only (min ~bootstrap_timeout+600s, capped at 7200), no explicit baseline_hold sleep."
        ),
    )
    parser.add_argument("--fault-profile", default=os.getenv("FAULT_PROFILE", "anomaly-concurrency-spike"))
    parser.add_argument("--load-profile", default=os.getenv("LOAD_PROFILE", "high"))
    parser.add_argument(
        "--normal-sec",
        type=int,
        default=int(os.getenv("NORMAL_SEC", "0")),
        help="Unused (CLI compatibility only).",
    )
    parser.add_argument(
        "--load-sec",
        type=int,
        default=int(os.getenv("LOAD_SEC", "0")),
        help="Unused (CLI compatibility).",
    )
    parser.add_argument("--chaos-sec", type=int, default=int(os.getenv("CHAOS_SEC", "60")))
    parser.add_argument("--cooldown-sec", type=int, default=int(os.getenv("COOLDOWN_SEC", "60")))
    parser.add_argument("--bootstrap-timeout-sec", type=int, default=int(os.getenv("BOOTSTRAP_TIMEOUT_SEC", "1800")))
    parser.add_argument("--cpu-workers", type=int, default=int(os.getenv("CHAOS_CPU_WORKERS", "2")))
    parser.add_argument("--mem-mb", type=int, default=int(os.getenv("CHAOS_MEM_MB", "1024")))
    parser.add_argument("--bottleneck-replicas", type=int, default=int(os.getenv("CHAOS_BOTTLENECK_REPLICAS", "2")))
    parser.add_argument(
        "--bootstrap-nb-threads",
        type=int,
        default=None,
        help="Optional threads= passed to NoSQLBench for bootstrap /start_nosqlbench (omit for chaos-injector defaults).",
    )
    parser.add_argument(
        "--bootstrap-nb-pop-end",
        type=int,
        default=None,
        help="Optional pop_end for bootstrap (profiles that honor pop_end, e.g. compaction-pressure).",
    )
    parser.add_argument(
        "--nb-threads",
        type=int,
        default=None,
        help="Optional threads= for anomaly-phase /start_nosqlbench.",
    )
    parser.add_argument(
        "--nb-pop-end",
        type=int,
        default=None,
        help="Optional pop_end for anomaly NoSQLBench profile.",
    )
    parser.add_argument(
        "--nb-parallel-jobs",
        type=int,
        default=int(os.getenv("NB_PARALLEL_JOBS", os.getenv("STRESS_PARALLEL_JOBS", "4"))),
        help="Parallel NoSQLBench Jobs for the anomaly phase (default from NB_PARALLEL_JOBS or STRESS_PARALLEL_JOBS).",
    )
    parser.add_argument(
        "--bootstrap-nb-parallel-jobs",
        type=int,
        default=int(os.getenv("BOOTSTRAP_NB_PARALLEL_JOBS", os.getenv("BOOTSTRAP_STRESS_PARALLEL_JOBS", "1"))),
        help="Parallel NoSQLBench Jobs during bootstrap.",
    )
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "cassandra/artifacts"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID"))
    parser.add_argument(
        "--start-fault-profile",
        default=os.getenv("START_FAULT_PROFILE", ""),
        help="Optional chaos-injector /start_fault profile to run before anomaly NoSQLBench (e.g. short-cpu-spike).",
    )
    parser.add_argument(
        "--start-fault-duration-sec",
        type=float,
        default=float(os.getenv("START_FAULT_DURATION_SEC", "10")),
        help="duration_sec for /start_fault when --start-fault-profile is set (float supported).",
    )
    parser.add_argument(
        "--start-fault-target-mode",
        default=os.getenv("START_FAULT_TARGET_MODE", "one"),
        help="target_mode for /start_fault (one|all) when --start-fault-profile is set.",
    )
    parser.add_argument(
        "--start-fault-target-pod",
        default=os.getenv("START_FAULT_TARGET_POD", "cassandra-0"),
        help="target_pod for /start_fault when target_mode=one (empty to auto-pick).",
    )
    parser.add_argument(
        "--skip-report",
        action="store_true",
        help="Do not run reporting/generate_report.py after the run (default: report is generated).",
    )
    parser.add_argument(
        "--report-chaos-min-scored",
        type=int,
        default=int(os.getenv("REPORT_CHAOS_MIN_SCORED", "50")),
        help="Quality gate: minimum chaos-phase scored samples for generate_report.py.",
    )
    parser.add_argument(
        "--report-max-fp",
        type=int,
        default=int(os.getenv("REPORT_MAX_FP", "10")),
        help="Acceptance: max false-positive alarms outside chaos window for generate_report.py.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    runner = NoSQLBenchScenarioRunner(args)
    runner.run()


if __name__ == "__main__":
    main()
