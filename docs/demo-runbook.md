# Demo Runbook

## Pre-demo Checklist

1. `make demo-preflight`
2. Verify Cassandra pods are Ready (`cassandra-0` … `cassandra-N-1` for your replica count).
3. Verify simulator, learner, and chaos injector are Running.
4. Verify Prometheus can scrape Cassandra and simulator.
5. Verify context is not `docker-desktop`/`kind` and at least 3 worker nodes are Ready.
6. **Mitigation track (optional):** fourth worker Ready (hot spare), plan StatefulSet scale **3 → 4** so `cassandra-3` can schedule during the demo.

## Local multi-terminal layout (orchestrator on laptop)

Typical terminals when driving the cluster from your machine. Exact loops also live in `docs/end-to-end-setup-and-run.md` §6.

| # | Role | Command |
| --- | --- | --- |
| 1 | Simulator | `while true; do kubectl port-forward -n cassandra-lab svc/cassandra-simulator 8080:8080; sleep 1; done` |
| 2 | UBL learner | `while true; do kubectl port-forward -n cassandra-lab svc/ubl-learner 8100:8100; sleep 1; done` |
| 3 | Chaos injector | `while true; do kubectl port-forward -n cassandra-lab svc/chaos-injector 8200:8200; sleep 1; done` |
| 4 | Grafana | `while true; do kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80; sleep 1; done` → `http://localhost:3000` |
| 5 | Prometheus | Discover server Service with `kubectl -n monitoring get svc` (filter name/prometheus), then `kubectl port-forward -n monitoring svc/<NAME> 9090:9090` (often `kube-prom-stack-kube-prome-prometheus`) |
| 6 (optional) | Live alarms | `while true; do date -u; curl -sS "http://localhost:8100/alarms?limit=20"; echo; sleep 1; done` |
| 7 | **Elastic replicas (D + F)** | Start **before** or **as** chaos begins — see below |

Health check after 1–3:

`curl -sS http://localhost:8080/health && curl -sS http://localhost:8100/health && curl -sS http://localhost:8200/health`

**Alarms:** `GET /alarms` can retain older items; **do not** treat `count > 0` alone as “mitigate now”. Use [`scripts/cassandra_elastic_replicas.sh`](../scripts/cassandra_elastic_replicas.sh) (default: **new** `phase=="chaos"` alarm since script start) or rely on Grafana/SLO.

### Terminal 7 — scale out then scale in (one script)

From `cassandra/`, with **8100** and **9090** forwards up:

```bash
export LEARNER_BASE=http://localhost:8100
export PROMETHEUS_BASE=http://localhost:9090
export PROMQL='vector(0)'
export SLO_THRESHOLD=1
export SLO_COMPARISON=lt
export STABLE_OK_SEC=15
bash ./scripts/cassandra_elastic_replicas.sh
```

Set real **`PROMQL`** / **`SLO_THRESHOLD`** for production-style scale-in. Optional: `SCALE_OUT_MODE=prom_bad` or `both` (see script header). `make elastic-cassandra-replicas` runs the same script without extra env.

## Live Demo Sequence

1. Explain architecture (Cassandra cluster + simulator + learner + chaos injector + orchestrator).
2. Start port-forwards (table above), then a scenario:
   - In-cluster / scripted: `bash ./scripts/run_strict_validation.sh bottleneck-like high`
   - **Local:** `python3 orchestrator/run_scenario.py --output-dir ./artifacts --fault-profile anomaly-hot-partition --load-profile high` (see `--help`).
3. During run, show phase transitions, active fault, learner `GET /alarms` / `GET /report`, Grafana.
4. **Phases D + F:** run `cassandra_elastic_replicas.sh` (terminal 7) so scale-out tracks **new chaos alarms** (or Prometheus `prom_bad`), then scale-in uses sustained SLO OK on Prometheus.
5. After completion: `artifacts/<run-id>/final_report.md` and `final_report.json`.

## Expected Milestones

- **A:** Bootstrap training completes (learner `ready`).
- **B:** Target load + chaos fault for the configured window.
- **C:** Learner alarms + lead time in report when alignment allows.
- **D + F:** Elastic replica cycle completes without scaling on stale alarms (default mode).
- **E:** Grafana backs the SLO / recovery narrative.

## Fallback Strategy

If chosen fault profile fails:

1. `curl -X POST http://localhost:8200/reset_all`
2. Re-run with another supported profile (see `chaos-injector/main.py` `valid_profiles`), e.g. `anomaly-concurrency-spike` or alias `cpuhog-like`:
   - `bash ./scripts/run_demo_mode.sh cpuhog-like high`
3. If still unstable, run baseline no-fault scenario and present stored artifacts from prior successful run.
