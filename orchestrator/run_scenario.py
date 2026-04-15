import argparse
import json
import os
import time
from dataclasses import dataclass, asdict
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
        self.run_id = args.run_id or f"scenario-{int(self.run_started_at)}"
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
                # Port-forward/service endpoints can flap briefly during rollouts.
                # Keep waiting within the bootstrap timeout instead of aborting run.
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
        self._record("run_start", {"run_id": self.run_id, "profile": self.args.load_profile, "fault_profile": self.args.fault_profile})

        sim_health = self._get(self.simulator_base, "/health")
        learner_health = self._get(self.learner_base, "/health")
        chaos_health = self._get(self.chaos_base, "/health")
        self._record("health_check", {"simulator": sim_health, "learner": learner_health, "chaos": chaos_health})

        self._post(self.learner_base, "/reset")
        self._post(self.chaos_base, "/reset_all")
        self._post(self.simulator_base, "/reset-metrics")
        self._post(self.simulator_base, "/resume")
        self._post(self.simulator_base, "/load", {"profile": "low"})
        self._post(self.learner_base, "/phase", {"phase": "normal"})

        self._record("bootstrap_wait_start", {"timeout_sec": self.args.bootstrap_timeout_sec})
        self._wait_learner_ready(self.args.bootstrap_timeout_sec)
        self._record("bootstrap_wait_end", {})

        self._sleep_phase(Phase("normal", self.args.normal_sec))

        self._post(self.learner_base, "/phase", {"phase": "load"})
        self._post(self.simulator_base, "/load", {"profile": self.args.load_profile})
        self._sleep_phase(Phase("load", self.args.load_sec))

        self._post(self.learner_base, "/phase", {"phase": "chaos"})
        fault_start_payload = self._post(
            self.chaos_base,
            "/start_fault",
            {
                "profile": self.args.fault_profile,
                "duration_sec": self.args.chaos_sec,
                "cpu_workers": self.args.cpu_workers,
                "mem_mb": self.args.mem_mb,
                "replicas": self.args.bottleneck_replicas,
            },
        )
        self._record("fault_start", fault_start_payload)
        self._sleep_phase(Phase("chaos", self.args.chaos_sec))
        fault_stop_payload = self._post(self.chaos_base, "/stop_fault", {"profile": self.args.fault_profile})
        self._record("fault_stop", fault_stop_payload)

        self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        self._post(self.simulator_base, "/load", {"profile": "medium"})
        self._sleep_phase(Phase("cooldown", self.args.cooldown_sec))

        learner_status = self._get(self.learner_base, "/status")
        learner_report = self._get(self.learner_base, "/report")
        score_stream = self._get(self.learner_base, "/score-stream?limit=5000")
        alarms = self._get(self.learner_base, "/alarms?limit=5000")
        simulator_metrics = self._get(self.simulator_base, "/metrics")

        run_finished = _now()
        summary = {
            "run_id": self.run_id,
            "started_at": self.run_started_at,
            "finished_at": run_finished,
            "duration_sec": round(run_finished - self.run_started_at, 2),
            "fault_profile": self.args.fault_profile,
            "load_profile": self.args.load_profile,
            "phase_durations": {
                "normal_sec": self.args.normal_sec,
                "load_sec": self.args.load_sec,
                "chaos_sec": self.args.chaos_sec,
                "cooldown_sec": self.args.cooldown_sec,
            },
            "injection_profile": {
                "fault_profile": self.args.fault_profile,
                "target_namespace": self.args.target_namespace,
                "cpu_workers": self.args.cpu_workers,
                "mem_mb": self.args.mem_mb,
                "bottleneck_replicas": self.args.bottleneck_replicas,
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
    parser = argparse.ArgumentParser(description="Run normal/load/chaos/cooldown scenario.")
    parser.add_argument("--simulator-base", default=os.getenv("SIMULATOR_BASE", "http://localhost:8080"))
    parser.add_argument("--learner-base", default=os.getenv("LEARNER_BASE", "http://localhost:8100"))
    parser.add_argument("--chaos-base", default=os.getenv("CHAOS_BASE", "http://localhost:8200"))
    parser.add_argument("--target-namespace", default=os.getenv("TARGET_NAMESPACE", "cassandra-lab"))
    parser.add_argument("--fault-profile", default=os.getenv("FAULT_PROFILE", "network-congestion-like"))
    parser.add_argument("--load-profile", default=os.getenv("LOAD_PROFILE", "high"))
    parser.add_argument("--normal-sec", type=int, default=int(os.getenv("NORMAL_SEC", "60")))
    parser.add_argument("--load-sec", type=int, default=int(os.getenv("LOAD_SEC", "60")))
    parser.add_argument("--chaos-sec", type=int, default=int(os.getenv("CHAOS_SEC", "120")))
    parser.add_argument("--cooldown-sec", type=int, default=int(os.getenv("COOLDOWN_SEC", "60")))
    parser.add_argument("--bootstrap-timeout-sec", type=int, default=int(os.getenv("BOOTSTRAP_TIMEOUT_SEC", "1800")))
    parser.add_argument("--cpu-workers", type=int, default=int(os.getenv("CHAOS_CPU_WORKERS", "2")))
    parser.add_argument("--mem-mb", type=int, default=int(os.getenv("CHAOS_MEM_MB", "1024")))
    parser.add_argument("--bottleneck-replicas", type=int, default=int(os.getenv("CHAOS_BOTTLENECK_REPLICAS", "2")))
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "cassandra/artifacts"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID"))
    return parser


def main():
    args = build_parser().parse_args()
    runner = ScenarioRunner(args)
    runner.run()


if __name__ == "__main__":
    main()
