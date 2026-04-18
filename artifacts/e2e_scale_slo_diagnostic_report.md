# End-to-end scale and SLO diagnostic report

**Generated:** workspace evidence + live cluster snapshot (read-only).  
**Scope:** Answer whether 3→4→3 occurred, why `cassandra-3` may be absent from Grafana, UBL vs SLO, VM capacity, and guardrails—per the diagnostic plan.

---

## 1. Run metadata

| Item | Value |
|------|--------|
| Elastic event log (workspace) | `cassandra/artifacts/elastic_replica_events_20260417T194532Z.jsonl` |
| Scenario artifacts referenced | `stress-ramp-s2-cpu-v2`, `concurrency-spike-demo` (`run_summary.json`) |
| `cassandra_elastic_replicas.sh` | One recorded cycle in JSONL (see §4). Script is **not** invoked by `orchestrator/run_scenario.py`; it must run in a separate terminal. |

---

## 2. Did scale up / scale down happen (3→4→3)?

### From elastic JSONL (authoritative for automation)

Events in `elastic_replica_events_20260417T194532Z.jsonl`:

| UTC time | Event | Detail |
|----------|--------|--------|
| 2026-04-17T19:45:32Z | `cycle_started` | `mode=chaos_alarm max=4 baseline=3` |
| 2026-04-17T20:14:20Z | `scale_out_signal` | `reason=chaos_alarm` |
| 2026-04-17T20:14:20Z | `scale_up` | `to=4` |
| 2026-04-17T20:15:24Z | `rollout_up_complete` | `replicas=4` |
| 2026-04-17T20:17:26Z | `slo_stable` | `value=0.0` |
| 2026-04-17T20:17:26Z | `scale_down` | `to=3` |
| 2026-04-17T20:17:26Z | `rollout_down_complete` | `replicas=3` |
| 2026-04-17T20:17:28Z | `cycle_complete` | `success=true` |

**Conclusion:** For this recorded run, **yes** — full **3→4→3** with chaos-alarm-driven scale-out and Prometheus-gated scale-in completed (~29 minutes from `cycle_started` to `scale_out_signal`, then ~2 minutes on 4 replicas before scale-in).

### From cluster snapshot (current)

At report generation time:

- `kubectl -n cassandra-lab get statefulset cassandra`: **spec.replicas = 3**, readyReplicas consistent with 3.
- Pods: `cassandra-0`, `cassandra-1`, `cassandra-2` only — **no `cassandra-3`** (expected if scale-in already ran or no scale-out occurred for the current window).

**If you only ran the orchestrator:** replicas can stay at 3 forever; **UBL alarms alone do not scale** the StatefulSet.

---

## 3. Why you might not see `cassandra-3` in Grafana

| Cause | How to confirm |
|--------|----------------|
| **Replicas never reached 4** | `kubectl get sts -n cassandra-lab cassandra` during chaos; elastic JSONL lacks `scale_up`. |
| **Elastic script not running** or **started after chaos** | No `scale_out_signal` in JSONL; default `chaos_alarm` needs a **new** `phase==chaos` alarm after script start (`WATCH_START_TS`). |
| **Scale-in completed** before you looked | JSONL shows `scale_down`; Grafana time range must include the mitigation window (~20:14–20:17Z in sample). |
| **`cassandra-3` Pending** (capacity, PVC, affinity) | When `replicas=4`, `kubectl describe pod -n cassandra-lab cassandra-3` (current snapshot: pod **NotFound** at 3 replicas). |
| **Dashboard PromQL** filters only `cassandra-[0-2]` | Inspect panel query / legend. |

---

## 4. VM / cluster capacity (hot spare readiness)

### Nodes

- **cp1** (control-plane) + **w1–w4** (workers), all **Ready**.
- **w4** present and Ready (~28h age in snapshot) — aligns with “hot spare worker” narrative.

### Per-worker shape (sample)

| Node | Capacity (from describe) | Notes |
|------|----------------------------|--------|
| w1–w4 | **2 CPU**, **~4004388Ki** memory allocatable | Typical ~4Gi class VM per worker. |
| w1, w2 | Higher allocated requests (Cassandra pods scheduled there in snapshot). | |
| w3 | Lower allocated (spare headroom). | |
| w4 | Moderate allocated — **room remains** for another pod class (e.g. fourth Cassandra) given 2 CPU / ~4Gi node. |

**Conclusion:** Capacity for a **fourth** Cassandra pod is **plausible** on this cluster (especially w3/w4 headroom). If `cassandra-3` had been Pending, the next check would be `describe pod` events (volume binding, anti-affinity, insufficient CPU).

---

## 5. Did anomaly injection hit “SLO violation”?

### UBL (learner) — independent signal

| Run | `fault_profile` | `alarm_count` (from `run_summary.json`) |
|-----|-----------------|------------------------------------------|
| `stress-ramp-s2-cpu-v2` | `anomaly-concurrency-spike` (1000 threads, 5M pop) | **126** |
| `concurrency-spike-demo` | `anomaly-concurrency-spike` (chaos defaults via orchestrator payload) | **21** |

UBL can show **strong** or **moderate** anomaly pressure depending on threads/duration and cluster state.

### Prometheus “SLO” used by elastic scale-in

Recorded `slo_stable` detail: **`value=0.0`**.

That matches the **demo** pattern from docs: `PROMQL='vector(0)'` with `SLO_THRESHOLD=1` and `SLO_COMPARISON=lt` → value is **always** in the OK band. Scale-in then only waits **hysteresis** (`STABLE_OK_SEC`); it does **not** prove a real latency/error SLO recovered.

**Live spot-check (instant query at report time):**

- `vector(0)` → **0** (OK vs threshold 1).
- Example Tier-A style probe: `max(sum(rate(container_cpu_usage_seconds_total{namespace="cassandra-lab",pod=~"cassandra-[0-9]+"}[2m])) by (pod))` → **~0.37** cores max in snapshot (informational; not your official SLO unless you define it as such).

**Conclusion:** **UBL alarms do not imply your Grafana SLO query went “bad.”** To prove SLO breach / recovery you must record **your** chosen `PROMQL` over the chaos interval (Grafana Explore or Prometheus range query), not rely on `vector(0)` for production-style narrative.

---

## 6. Guardrails (`ramp_guardrail_gate.sh`)

- The guardrail script is a **manual** “advance / sanity” gate between stress stages; it **does not** call `kubectl scale` and does **not** block elastic scaling unless you choose to stop the demo based on its exit code.
- If default PromQL inside the script were wrong, you could see false FAIL; fix env overrides per `docs/end-to-end-setup-and-run.md`. **Not** the root cause of missing `cassandra-3` unless you never scaled out.

---

## 7. Verdict vs final goal

| Goal step | Status (from evidence) |
|-----------|-------------------------|
| Stress → chaos Jobs | **Yes** — chaos-injector drives `cassandra-stress`; scenario artifacts exist. |
| UBL alarms in chaos | **Yes** for concurrency-style runs (e.g. 126 / 21 alarms). |
| Mitigation 3→4 on alarm | **Yes** for recorded elastic JSONL (`scale_up` to 4). Requires **running** `cassandra_elastic_replicas.sh` with correct timing. |
| Observable `cassandra-3` | **Yes** during mitigation window only; **absent** at steady 3 replicas. |
| SLO-based scale-in narrative | **Weak** if using demo `vector(0)` — scale-in is time-gated OK, not “metric recovered.” |
| E2E “production honest” | **Partial** until real `PROMQL` + threshold match dashboards and are captured during chaos. |

### Top gaps to close next

1. Export **real** `PROMQL` / `SLO_THRESHOLD` into `cassandra_elastic_replicas.sh` env and document the same query in Grafana.
2. Align **Grafana time range** with elastic JSONL timestamps when proving `cassandra-3` existed.
3. If scale-out never fires: confirm script start **before** chaos and check `/alarms` phase and `ts` vs `WATCH_START_TS`.

---

## Appendix: Commands used

```bash
kubectl -n cassandra-lab get statefulset cassandra -o jsonpath='{.spec.replicas} ...'
kubectl -n cassandra-lab get pods -l app=cassandra -o wide
kubectl get nodes -o wide
kubectl describe node w1   # repeat w2–w4
kubectl -n cassandra-lab describe pod cassandra-3   # NotFound when replicas=3
curl -sS 'http://localhost:9090/api/v1/query?query=vector(0)'
curl -sS 'http://localhost:9090/api/v1/query?query=max(sum(rate(...)))'
```
