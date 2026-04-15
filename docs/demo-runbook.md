# Demo Runbook

## Pre-demo Checklist

1. `make demo-preflight`
2. Verify Cassandra pods are Ready.
3. Verify simulator, learner, and chaos injector are Running.
4. Verify Prometheus can scrape Cassandra and simulator.
5. Verify context is not `docker-desktop`/`kind` and at least 3 worker nodes are Ready.

## Live Demo Sequence

1. Explain architecture (Cassandra cluster + simulator + learner + chaos injector + orchestrator).
2. Start demo scenario:
   - `bash ./scripts/run_strict_validation.sh bottleneck-like high`
3. During run, show:
   - phase transitions
   - active fault profile
   - learner alarms
4. After completion, open:
   - `artifacts/<run-id>/final_report.md`
   - `artifacts/<run-id>/final_report.json`

## Expected Milestones

- Bootstrap training completes (learner ready).
- Load phase increases activity.
- Chaos phase introduces fault profile.
- Learner raises anomaly alarms.
- Cooldown shows partial recovery.
- Report bundle generated automatically.

## Fallback Strategy

If chosen fault profile fails:

1. `curl -X POST http://localhost:8200/reset_all`
2. Re-run with `cpuhog-like`:
   - `bash ./scripts/run_demo_mode.sh cpuhog-like high`
3. If still unstable, run baseline no-fault scenario and present stored artifacts from prior successful run.
