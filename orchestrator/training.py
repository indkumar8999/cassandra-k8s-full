import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional


def _now() -> float:
    return time.time()


@dataclass
class BootstrapArtifacts:
    baseline_fault_start: Dict[str, Any]
    baseline_fault_stop: Dict[str, Any]
    learner_status: Dict[str, Any]
    som_snapshot: Dict[str, Any]
    som_snapshot_path: Path


def wait_learner_ready(
    *,
    get_status: Callable[[], Dict[str, Any]],
    record: Callable[[str, Optional[Dict[str, Any]]], None],
    timeout_sec: int,
    poll_sec: float = 2.0,
) -> Dict[str, Any]:
    started = _now()
    last_status: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None

    while _now() - started < timeout_sec:
        try:
            status = get_status()
            last_status = status
            if status.get("ready"):
                record("learner_ready", status)
                return status
        except Exception as ex:
            last_error = str(ex)
        time.sleep(poll_sec)

    detail = {"timeout_sec": timeout_sec}
    if last_status is not None:
        detail["last_status"] = last_status
    if last_error is not None:
        detail["last_error"] = last_error
    record("learner_ready_timeout", detail)
    return last_status or {"ready": False, "error": "timeout", **detail}


def save_som_snapshot(*, run_dir: Path, som_snapshot: Dict[str, Any], filename: str) -> Path:
    out = run_dir / filename
    out.write_text(json.dumps(som_snapshot, indent=2), encoding="utf-8")
    return out


def bootstrap_train_and_save_som(
    *,
    simulator_base: str,
    learner_base: str,
    chaos_base: str,
    bootstrap_sim_profile: str,
    bootstrap_fault_profile: str,
    bootstrap_sec: int,
    bootstrap_timeout_sec: int,
    run_dir: Path,
    post: Callable[[str, str, Optional[Dict[str, Any]]], Dict[str, Any]],
    get: Callable[[str, str], Dict[str, Any]],
    record: Callable[[str, Optional[Dict[str, Any]]], None],
    post_chaos_stop_fault: Callable[[str], Dict[str, Any]],
    sleep_phase: Optional[Callable[[str, int], None]] = None,
    som_snapshot_filename: str = "som_trained_snapshot.json",
) -> BootstrapArtifacts:
    """Run the Scenario-A bootstrap/training phase and persist SOM snapshot.

    This function is intentionally orchestration-only: it drives the simulator + chaos injector
    and queries the learner for readiness + SOM export.
    """

    # Keep simulator low during bootstrap to isolate baseline training.
    post(simulator_base, "/load", {"profile": bootstrap_sim_profile})

    # Bootstrap uses normal phase and a fixed-duration baseline fault.
    post(learner_base, "/phase", {"phase": "normal"})
    baseline_body: Dict[str, Any] = {"profile": bootstrap_fault_profile, "duration_sec": bootstrap_sec}
    baseline_start = post(chaos_base, "/start_fault", baseline_body)
    record("bootstrap_fault_start", baseline_start)

    if sleep_phase is not None:
        sleep_phase("bootstrap", bootstrap_sec)
    else:
        record("phase_start", {"phase": "bootstrap", "duration_sec": bootstrap_sec})
        if bootstrap_sec > 0:
            time.sleep(bootstrap_sec)
        record("phase_end", {"phase": "bootstrap"})

    baseline_stop = post_chaos_stop_fault(bootstrap_fault_profile)
    record("bootstrap_fault_stop", baseline_stop)

    # Wait for learner to report ready (training can lag behind the fault window).
    record("bootstrap_wait_start", {"timeout_sec": bootstrap_timeout_sec})
    learner_status = wait_learner_ready(
        get_status=lambda: get(learner_base, "/status"),
        record=record,
        timeout_sec=max(int(bootstrap_timeout_sec), 1),
    )
    record("bootstrap_wait_end", {"ready": bool(learner_status.get("ready"))})

    # Export + persist trained SOM snapshot (weights + area map).
    som_snapshot: Dict[str, Any] = {}
    try:
        som_snapshot = get(learner_base, "/export/som-snapshot")
    except Exception as ex:
        som_snapshot = {
            "error": str(ex),
            "note": "Learner did not expose /export/som-snapshot or SOM not trained.",
            "learner_status": learner_status,
        }
    som_path = save_som_snapshot(run_dir=run_dir, som_snapshot=som_snapshot, filename=som_snapshot_filename)
    record("som_snapshot_saved", {"path": str(som_path)})

    return BootstrapArtifacts(
        baseline_fault_start=baseline_start,
        baseline_fault_stop=baseline_stop,
        learner_status=learner_status,
        som_snapshot=som_snapshot,
        som_snapshot_path=som_path,
    )
