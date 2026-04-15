import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Optional, Tuple


def _load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _chaos_window(events: List[Dict]) -> Tuple[Optional[float], Optional[float]]:
    start = None
    stop = None
    for event in events:
        if event.get("event") == "fault_start":
            start = event.get("ts")
        elif event.get("event") == "fault_stop":
            stop = event.get("ts")
    return start, stop


def _classify_alarms(alarms: List[Dict], chaos_start: Optional[float], chaos_stop: Optional[float]):
    tp = 0
    fp = 0
    during = []
    for alarm in alarms:
        ts = alarm.get("ts", 0)
        in_window = (
            chaos_start is not None
            and chaos_stop is not None
            and chaos_start <= ts <= chaos_stop
        )
        if in_window:
            tp += 1
            during.append(alarm)
        else:
            fp += 1
    fn = 0 if tp > 0 else 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    return {"tp": tp, "fp": fp, "fn_proxy": fn, "precision": precision, "recall": recall, "f1": f1, "during": during}


def _lead_times(alarms: List[Dict], chaos_start: Optional[float]):
    if chaos_start is None:
        return {"first_detection_delay_sec": None, "mean_detection_delay_sec": None, "median_detection_delay_sec": None}
    delays = [alarm["ts"] - chaos_start for alarm in alarms if alarm.get("ts") is not None and alarm["ts"] >= chaos_start]
    if not delays:
        return {"first_detection_delay_sec": None, "mean_detection_delay_sec": None, "median_detection_delay_sec": None}
    return {
        "first_detection_delay_sec": min(delays),
        "mean_detection_delay_sec": mean(delays),
        "median_detection_delay_sec": median(delays),
    }


def _cause_ranking(alarms: List[Dict]):
    cause_counter = Counter()
    for alarm in alarms:
        for cause in alarm.get("causes", []):
            cause_counter[cause] += 1
    return cause_counter.most_common(10)


def _scored_by_phase(score_items: List[Dict]) -> Dict[str, int]:
    phase_counts = Counter()
    for item in score_items:
        phase_counts[item.get("phase", "unknown")] += 1
    result = {phase: int(phase_counts.get(phase, 0)) for phase in ("normal", "load", "chaos", "cooldown")}
    result["unknown"] = int(phase_counts.get("unknown", 0))
    return result


def _quality_gate(scored_by_phase: Dict[str, int], chaos_min_scored: int) -> Dict:
    chaos_scored = int(scored_by_phase.get("chaos", 0))
    passed = chaos_scored >= chaos_min_scored
    return {
        "passed": passed,
        "chaos_scored_samples": chaos_scored,
        "chaos_min_scored_required": chaos_min_scored,
        "message": "ok" if passed else f"chaos scored samples too low: {chaos_scored} < {chaos_min_scored}",
    }


def _acceptance(report: Dict, max_fp: int) -> Dict:
    cls = report["classification"]
    lead = report["lead_time"]
    run_quality = report["run_quality"]
    checks = {
        "tp_during_chaos": cls.get("tp", 0) >= 1,
        "lead_time_present": lead.get("first_detection_delay_sec") is not None,
        "chaos_sample_gate_passed": run_quality.get("passed", False),
        "fp_within_limit": cls.get("fp", 0) <= max_fp,
    }
    passed = all(checks.values())
    return {
        "passed": passed,
        "max_fp_allowed": max_fp,
        "checks": checks,
    }


def _median_or_none(values: List[Optional[float]]) -> Optional[float]:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return float(median(valid))


def _run_dirs(root: Path) -> List[Path]:
    dirs: List[Path] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if (candidate / "run_summary.json").exists() and (candidate / "run_events.json").exists():
            dirs.append(candidate)
    return dirs


def render_markdown(report: Dict) -> str:
    lines = []
    lines.append("# Cassandra UBL Run Report")
    lines.append("")
    lines.append("## Run Metadata")
    lines.append(f"- Run ID: `{report['run_id']}`")
    lines.append(f"- Fault profile: `{report['fault_profile']}`")
    lines.append(f"- Load profile: `{report['load_profile']}`")
    lines.append(f"- Duration sec: `{report['duration_sec']}`")
    lines.append("")
    lines.append("## Fault Injection Profile (EDA)")
    inj = report["injection_profile"]
    lines.append(f"- Target namespace: `{inj.get('target_namespace')}`")
    lines.append(f"- CPU workers: `{inj.get('cpu_workers')}`")
    lines.append(f"- Memory MB: `{inj.get('mem_mb')}`")
    lines.append(f"- Bottleneck replicas: `{inj.get('bottleneck_replicas')}`")
    lines.append(f"- Commanded chaos window: `{report['chaos_window']}`")
    lines.append("")
    lines.append("## Detection Summary")
    cls = report["classification"]
    lines.append(f"- TP: `{cls['tp']}`")
    lines.append(f"- FP: `{cls['fp']}`")
    lines.append(f"- FN(proxy): `{cls['fn_proxy']}`")
    lines.append(f"- Precision: `{cls['precision']:.4f}`")
    lines.append(f"- Recall: `{cls['recall']:.4f}`")
    lines.append(f"- F1: `{cls['f1']:.4f}`")
    lines.append("")
    lines.append("## Lead-Time / Delay")
    lt = report["lead_time"]
    lines.append(f"- First detection delay sec: `{lt['first_detection_delay_sec']}`")
    lines.append(f"- Mean detection delay sec: `{lt['mean_detection_delay_sec']}`")
    lines.append(f"- Median detection delay sec: `{lt['median_detection_delay_sec']}`")
    lines.append("")
    lines.append("## SOM Runtime Metrics")
    som = report["som_metrics"]
    lines.append(f"- Training duration sec: `{som.get('training_duration_sec')}`")
    lines.append(f"- Bootstrap samples: `{som.get('bootstrap_collected_samples')}`")
    lines.append(f"- Avg scoring latency ms: `{som.get('avg_score_latency_ms')}`")
    lines.append(f"- BMU coverage count: `{som.get('bmu_coverage_count')}`")
    lines.append(f"- Scored by phase: `{som.get('scored_by_phase')}`")
    lines.append(f"- Dropped missing Tier A: `{som.get('total_samples_dropped_missing_tier_a')}`")
    lines.append(f"- Dropped missing Tier B: `{som.get('total_samples_dropped_missing_tier_b')}`")
    lines.append("")
    lines.append("## Run Quality Gate")
    quality = report["run_quality"]
    lines.append(f"- Passed: `{quality['passed']}`")
    lines.append(f"- Chaos scored samples: `{quality['chaos_scored_samples']}`")
    lines.append(f"- Chaos min required: `{quality['chaos_min_scored_required']}`")
    lines.append(f"- Message: `{quality['message']}`")
    lines.append("")
    lines.append("## Acceptance Criteria")
    acceptance = report["acceptance"]
    lines.append(f"- Passed: `{acceptance['passed']}`")
    lines.append(f"- Max FP allowed: `{acceptance['max_fp_allowed']}`")
    for check_name, check_pass in acceptance["checks"].items():
        lines.append(f"- {check_name}: `{check_pass}`")
    lines.append("")
    lines.append("## Top Cause Metrics")
    for name, count in report["cause_ranking_top10"]:
        lines.append(f"- `{name}`: `{count}`")
    if not report["cause_ranking_top10"]:
        lines.append("- No cause hints were emitted.")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Precision/recall are run-level indicators intended for comparative ablations.")
    lines.append("- FN is proxy-based (`1` if no alarm during chaos window; else `0`) for MVP comparability.")
    return "\n".join(lines)


def generate_ablation(runs_root: Path, chaos_min_scored: int, max_fp: int) -> Dict:
    run_dirs = _run_dirs(runs_root)
    grouped: Dict[Tuple, List[Dict]] = {}

    for run_dir in run_dirs:
        report = generate(run_dir, chaos_min_scored=chaos_min_scored, max_fp=max_fp)
        summary = _load_json(run_dir / "run_summary.json")
        inj = summary.get("injection_profile", {})
        key = (
            report.get("fault_profile"),
            report.get("load_profile"),
            inj.get("cpu_workers"),
            inj.get("mem_mb"),
            inj.get("bottleneck_replicas"),
        )
        grouped.setdefault(key, []).append(report)

    rows = []
    for key, items in grouped.items():
        fault_profile, load_profile, cpu_workers, mem_mb, bottleneck_replicas = key
        precision_vals = [item["classification"]["precision"] for item in items]
        recall_vals = [item["classification"]["recall"] for item in items]
        f1_vals = [item["classification"]["f1"] for item in items]
        lead_vals = [item["lead_time"]["first_detection_delay_sec"] for item in items]
        train_vals = [item["som_metrics"]["training_duration_sec"] for item in items]
        score_vals = [item["som_metrics"]["avg_score_latency_ms"] for item in items]
        bmu_vals = [item["som_metrics"]["bmu_coverage_count"] for item in items]
        chaos_scored_vals = [item["som_metrics"]["scored_by_phase"].get("chaos", 0) for item in items]
        tp_runs = sum(1 for item in items if item["classification"]["tp"] > 0)
        fp_runs = sum(1 for item in items if item["classification"]["fp"] > 0)
        quality_pass_runs = sum(1 for item in items if item["run_quality"]["passed"])
        acceptance_pass_runs = sum(1 for item in items if item["acceptance"]["passed"])

        rows.append(
            {
                "group": {
                    "fault_profile": fault_profile,
                    "load_profile": load_profile,
                    "cpu_workers": cpu_workers,
                    "mem_mb": mem_mb,
                    "bottleneck_replicas": bottleneck_replicas,
                },
                "run_count": len(items),
                "run_ids": [item["run_id"] for item in items],
                "median_metrics": {
                    "precision": _median_or_none(precision_vals),
                    "recall": _median_or_none(recall_vals),
                    "f1": _median_or_none(f1_vals),
                    "first_detection_delay_sec": _median_or_none(lead_vals),
                    "training_duration_sec": _median_or_none(train_vals),
                    "avg_score_latency_ms": _median_or_none(score_vals),
                    "bmu_coverage_count": _median_or_none(bmu_vals),
                    "chaos_scored_samples": _median_or_none(chaos_scored_vals),
                },
                "run_level_outcomes": {
                    "runs_with_tp": tp_runs,
                    "runs_with_fp": fp_runs,
                    "runs_passing_quality_gate": quality_pass_runs,
                    "runs_passing_acceptance": acceptance_pass_runs,
                },
            }
        )

    rows.sort(key=lambda row: (-row["run_count"], row["group"]["fault_profile"] or ""))
    return {"runs_root": str(runs_root), "group_count": len(rows), "groups": rows}


def render_ablation_markdown(report: Dict) -> str:
    lines = []
    lines.append("# Cassandra UBL Ablation Report")
    lines.append("")
    lines.append(f"- Runs root: `{report['runs_root']}`")
    lines.append(f"- Groups: `{report['group_count']}`")
    lines.append("")

    for idx, group in enumerate(report["groups"], start=1):
        cfg = group["group"]
        med = group["median_metrics"]
        outcomes = group["run_level_outcomes"]
        lines.append(f"## Group {idx}")
        lines.append(
            f"- Config: fault=`{cfg['fault_profile']}`, load=`{cfg['load_profile']}`, "
            f"cpu_workers=`{cfg['cpu_workers']}`, mem_mb=`{cfg['mem_mb']}`, "
            f"bottleneck_replicas=`{cfg['bottleneck_replicas']}`"
        )
        lines.append(f"- Run count: `{group['run_count']}`")
        lines.append(f"- Median precision/recall/F1: `{med['precision']}` / `{med['recall']}` / `{med['f1']}`")
        lines.append(f"- Median first detection delay sec: `{med['first_detection_delay_sec']}`")
        lines.append(f"- Median training sec: `{med['training_duration_sec']}`")
        lines.append(f"- Median score latency ms: `{med['avg_score_latency_ms']}`")
        lines.append(f"- Median BMU coverage: `{med['bmu_coverage_count']}`")
        lines.append(f"- Median chaos scored samples: `{med['chaos_scored_samples']}`")
        lines.append(f"- Runs with TP / FP: `{outcomes['runs_with_tp']}` / `{outcomes['runs_with_fp']}`")
        lines.append(f"- Runs passing quality gate: `{outcomes['runs_passing_quality_gate']}`")
        lines.append(f"- Runs passing acceptance: `{outcomes['runs_passing_acceptance']}`")
        lines.append(f"- Run IDs: `{', '.join(group['run_ids'])}`")
        lines.append("")
    return "\n".join(lines)


def generate(run_dir: Path, chaos_min_scored: int, max_fp: int) -> Dict:
    summary = _load_json(run_dir / "run_summary.json")
    events = _load_json(run_dir / "run_events.json").get("events", [])
    alarms = _load_json(run_dir / "alarms.json").get("items", [])
    learner_report = _load_json(run_dir / "learner_report.json")
    score_items = _load_json(run_dir / "score_stream.json").get("items", [])

    chaos_start, chaos_stop = _chaos_window(events)
    cls = _classify_alarms(alarms, chaos_start, chaos_stop)
    lead = _lead_times(cls["during"], chaos_start)
    causes = _cause_ranking(cls["during"])
    scored_by_phase = learner_report.get("scored_by_phase") or _scored_by_phase(score_items)
    run_quality = _quality_gate(scored_by_phase, chaos_min_scored=chaos_min_scored)

    result = {
        "run_id": summary.get("run_id"),
        "fault_profile": summary.get("fault_profile"),
        "load_profile": summary.get("load_profile"),
        "duration_sec": summary.get("duration_sec"),
        "injection_profile": summary.get("injection_profile", {}),
        "chaos_window": {"start_ts": chaos_start, "stop_ts": chaos_stop},
        "classification": {k: v for k, v in cls.items() if k != "during"},
        "lead_time": lead,
        "som_metrics": {
            "training_duration_sec": learner_report.get("training_duration_sec"),
            "bootstrap_collected_samples": learner_report.get("bootstrap_collected_samples"),
            "avg_score_latency_ms": learner_report.get("avg_score_latency_ms"),
            "bmu_coverage_count": learner_report.get("bmu_coverage_count"),
            "scored_by_phase": scored_by_phase,
            "total_samples_dropped_missing_tier_a": learner_report.get("total_samples_dropped_missing_tier_a"),
            "total_samples_dropped_missing_tier_b": learner_report.get("total_samples_dropped_missing_tier_b"),
        },
        "run_quality": run_quality,
        "cause_ranking_top10": causes,
    }
    result["acceptance"] = _acceptance(result, max_fp=max_fp)
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate report artifacts for scenario run directory.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-dir", help="Path to one orchestrator run directory.")
    target.add_argument("--runs-root", help="Path containing multiple run directories for ablation summary.")
    parser.add_argument("--chaos-min-scored", type=int, default=50, help="Minimum scored samples required during chaos.")
    parser.add_argument("--max-fp", type=int, default=10, help="Maximum false positives allowed for acceptance pass.")
    parser.add_argument("--fail-on-quality-gate", action="store_true", help="Exit non-zero if quality gate fails.")
    parser.add_argument("--fail-on-acceptance", action="store_true", help="Exit non-zero if acceptance criteria fail.")
    args = parser.parse_args()

    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")

        result = generate(run_dir, chaos_min_scored=args.chaos_min_scored, max_fp=args.max_fp)
        report_json_path = run_dir / "final_report.json"
        report_md_path = run_dir / "final_report.md"

        report_json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        report_md_path.write_text(render_markdown(result), encoding="utf-8")
        print(f"Report generated: {report_json_path}")
        print(f"Report generated: {report_md_path}")
        if args.fail_on_quality_gate and not result["run_quality"]["passed"]:
            raise SystemExit("Run quality gate failed.")
        if args.fail_on_acceptance and not result["acceptance"]["passed"]:
            raise SystemExit("Run acceptance criteria failed.")
        return

    runs_root = Path(args.runs_root)
    if not runs_root.exists():
        raise FileNotFoundError(f"Runs root not found: {runs_root}")

    result = generate_ablation(runs_root, chaos_min_scored=args.chaos_min_scored, max_fp=args.max_fp)
    report_json_path = runs_root / "ablation_report.json"
    report_md_path = runs_root / "ablation_report.md"
    report_json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    report_md_path.write_text(render_ablation_markdown(result), encoding="utf-8")
    print(f"Ablation report generated: {report_json_path}")
    print(f"Ablation report generated: {report_md_path}")


if __name__ == "__main__":
    main()
