import argparse
import json
import os
import subprocess
import sys
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

    def run(self):
        self._record("run_start", {"run_id": self.run_id})

        # Reset all services
        self._post(self.learner_base, "/reset")
        self._post(self.chaos_base, "/reset_all")
        self._post(self.simulator_base, "/reset-metrics")
        self._post(self.simulator_base, "/resume")

        # 1. Bootstrap phase (normal)
        self._post(self.simulator_base, "/load", {"profile": "low"})
        self._post(self.learner_base, "/phase", {"phase": "normal"})
        baseline_body = {"profile": "baseline-normal", "duration_sec": self.args.bootstrap_duration}
        baseline_start = self._post(self.chaos_base, "/start_fault", baseline_body)
        self._record("bootstrap_fault_start", baseline_start)
        self._sleep_phase(Phase("bootstrap", self.args.bootstrap_duration))
        baseline_stop = self._post_chaos_stop_fault("baseline-normal")
        self._record("bootstrap_fault_stop", baseline_stop)

        # 2. Chaos mode ON, then short CPU spike, then baseline-normal again
        self._post(self.learner_base, "/phase", {"phase": "chaos"})

        # Inject custom CPU spike (short, not an anomaly)
        self._record("custom_cpu_spike_start", {})
        cpu_spike_body = {"profile": "short-cpu-spike", "duration_sec": self.args.cpu_spike_duration}
        cpu_spike_start = self._post(self.chaos_base, "/start_fault", cpu_spike_body)
        self._record("custom_cpu_spike_injected", cpu_spike_start)
        self._sleep_phase(Phase("custom_cpu_spike", self.args.cpu_spike_duration))
        cpu_spike_stop = self._post_chaos_stop_fault("short-cpu-spike")
        self._record("custom_cpu_spike_end", cpu_spike_stop)

        # Run baseline-normal in chaos mode
        baseline_chaos_body = {"profile": "baseline-normal", "duration_sec": self.args.chaos_baseline_duration}
        baseline_chaos_start = self._post(self.chaos_base, "/start_fault", baseline_chaos_body)
        self._record("baseline_in_chaos_start", baseline_chaos_start)
        self._sleep_phase(Phase("baseline_in_chaos", self.args.chaos_baseline_duration))
        baseline_chaos_stop = self._post_chaos_stop_fault("baseline-normal")
        self._record("baseline_in_chaos_stop", baseline_chaos_stop)

        # Inject concurrency spike
        spike_body = {"profile": "anomaly-concurrency-spike", "duration_sec": self.args.concurrency_spike_duration}
        spike_start = self._post(self.chaos_base, "/start_fault", spike_body)
        self._record("concurrency_spike_start", spike_start)
        self._sleep_phase(Phase("concurrency_spike", self.args.concurrency_spike_duration))
        spike_stop = self._post_chaos_stop_fault("anomaly-concurrency-spike")
        self._record("concurrency_spike_stop", spike_stop)

        # Cooldown
        self._post(self.learner_base, "/phase", {"phase": "cooldown"})
        self._post(self.simulator_base, "/load", {"profile": "medium"})
        self._sleep_phase(Phase("cooldown", self.args.cooldown_duration))

        self._record("run_complete", {"run_dir": str(self.run_dir)})
        self._write_json("run_events.json", {"events": self.events})

    def _write_json(self, name: str, payload: Dict):
        out = self.run_dir / name
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def build_parser():
    parser = argparse.ArgumentParser(description="Custom scenario: bootstrap, chaos, baseline, spike, cooldown.")
    parser.add_argument("--simulator-base", default=os.getenv("SIMULATOR_BASE", "http://localhost:8080"))
    parser.add_argument("--learner-base", default=os.getenv("LEARNER_BASE", "http://localhost:8100"))
    parser.add_argument("--chaos-base", default=os.getenv("CHAOS_BASE", "http://localhost:8200"))
    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "cassandra/artifacts"))
    parser.add_argument("--run-id", default=os.getenv("RUN_ID"))
    parser.add_argument("--bootstrap-duration", type=int, default=int(os.getenv("BOOTSTRAP_DURATION", "60")), help="Bootstrap phase duration (seconds)")
    parser.add_argument("--chaos-baseline-duration", type=int, default=int(os.getenv("CHAOS_BASELINE_DURATION", "30")), help="Baseline-normal in chaos mode duration (seconds)")
    parser.add_argument("--concurrency-spike-duration", type=int, default=int(os.getenv("CONCURRENCY_SPIKE_DURATION", "30")), help="Concurrency spike duration (seconds)")
    parser.add_argument("--cpu-spike-duration", type=int, default=int(os.getenv("CPU_SPIKE_DURATION", "1")), help="Custom CPU spike duration (seconds)")
    parser.add_argument("--cooldown-duration", type=int, default=int(os.getenv("COOLDOWN_DURATION", "15")), help="Cooldown phase duration (seconds)")
    return parser

def main():
    args = build_parser().parse_args()
    runner = ScenarioRunner(args)
    runner.run()

if __name__ == "__main__":
    main()
