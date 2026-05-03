# UBL Setup

Author: Darsh Rank ([drank@ncsu.edu](mailto:drank@ncsu.edu))

This guide explains UBL implementation and setup.
It includes online inference service behavior and offline training workflow.
It is focused on technical setup and implementation details.
It does not discuss experiment outcomes.

## Scope

- Sources used in this guide:
  - `ubl-learner/`
  - `offline-training/`
  - `k8s/ubl-learner/`

## Implementation Overview

The learner follows a SOM-based UBL pipeline:

1. Collect per-replica infrastructure metrics.
2. Aggregate metrics into a cluster-level feature vector.
3. Normalize each feature with frozen per-feature caps.
4. Map the vector to a SOM Best Matching Unit (BMU).
5. Use local SOM area roughness as anomaly score.
6. Trigger alarms only after streak-based debounce.
7. Rank likely cause channels using local normal neighbors.

The report defines this as an unsupervised behavior learning path.

## How the report maps to this code

The project report is generated from `reporting/ADS_Project_final_report.tex` (methodology: SOM setup, algorithms, hyperparameters, cause inference, live inference). That narrative matches this repository’s implementation in `ubl-learner/main.py`: rectangular **R×C** lattice, **D=3** after replica averaging over the three infrastructure channels, **L2** BMU, Gaussian neighborhood with **radius** mask, **4-neighbor** area map, optional **K-sample** smoothing (`SMOOTH_K`), **streak** alarming, and neighbor-vote **cause** hints. Deviations called out in this doc: **τ** is the percentile of **flattened `area_map`** values (not necessarily the percentile of per-tick BMU scores); training picks one fold by **minimum validation sum of BMU areas**; optional **online `train_step`** updates weights outside `chaos` when enabled.

## UBL Learner service layout

Main files:

- `ubl-learner/main.py` — SOM, Prometheus polling, HTTP API, Prometheus client metrics
- `ubl-learner/requirements.txt`
- `ubl-learner/Dockerfile` — copies `main.py` and bakes `*.json` snapshots under `/models/`
- `k8s/ubl-learner/ubl-learner-*.yaml`

Runtime shape:

- On import, `LearnerState` starts a **daemon thread** (`_poll_loop`) that sleeps `POLL_SEC` between cycles.
- HTTP handlers take `state.lock` only for short critical sections; Prometheus calls for `/score-stream` SLO enrichment run **outside** the lock to avoid stalls.
- If a snapshot file exists (`UBL_SNAPSHOT_PATH` or default `/models/som_trained_snapshot.json`), the learner loads it at startup and sets `trained` / `ready` without waiting for bootstrap.

## Replica metrics feature contract and Prometheus queries

### Canonical metric names in code

The report uses a three-channel cluster vector after averaging across Cassandra replicas. In code, the **canonical feature order** is fixed to three strings (CPU usage in cores, memory working set in bytes, combined disk read/write throughput in bytes per second). The exact spellings used in JSON, snapshots, and PromQL map keys live in `ubl-learner/main.py` alongside the per-pod query templates (search for `NODE_QUERY_TEMPLATES` and `AVG_FEATURES`).

### Per-pod PromQL templates

For each pod name in `CASSANDRA_PODS`, the learner issues instant queries by substituting `__NAMESPACE__` → `TARGET_NAMESPACE` and `__POD__` → the pod. The template map in `main.py` has one entry per base metric; the table states the PromQL **shape** (open `ubl-learner/main.py` for the exact query strings and key names):

| Channel (concept) | PromQL idea (simplified) |
| ------------------ | ------------------------ |
| CPU usage (cores) | `sum(rate(container_cpu_usage_seconds_total{namespace,pod}[1m]))` |
| Memory working set (bytes) | `sum(container_memory_working_set_bytes{namespace,pod})` |
| Disk throughput (bytes/s) | sum of **read + write** byte rates from `container_fs_reads_bytes_total` and `container_fs_writes_bytes_total` over `[1m]` |

Each query result is stored under a composite key `{base}__{pod}` where `base` is the corresponding key from that map in `main.py` (suffix `__` plus the pod name, e.g. `…__cassandra-0`).

### Replica averaging (cluster vector **x**(t))

For training and live scoring, the learner averages, per base metric, the values present across `CASSANDRA_PODS` (averaging helper on `LearnerState` in `main.py`). If some pods are missing a value, the mean uses **only pods that returned a number** (not imputed zeros for missing pods).

### Sample validity and coverage gate

A poll is **invalid** for training or scoring if, for any of the three base metrics, too few pods returned a value: fewer than the configured minimum fraction of `CASSANDRA_PODS` (default **0.67** in `main.py`). Missing keys are listed in `missing_required` and `quality_valid` is false. Invalid samples are:

- still appended during bootstrap collection, but filtered out of `_train()` via `quality_valid`
- not scored when `trained` is true (`_poll_loop` increments the missing-metrics drop counter in source instead)

This matches the report rule: do not silently impute mandatory signals.

## Normalization (capacity-style caps)

### Training-time caps

After collecting at least `BOOTSTRAP_SAMPLES` valid bootstrap samples, `_train()` builds raw rows (three averages per sample), optionally applies `**_apply_training_smoothing`** (same window `SMOOTH_K` as live smoothing: trailing mean over the training sequence index), then:

1. `observed_max[j]` = max over training columns.
2. `capacity_max` from `_capacity_norm_max()` — best-effort PromQL against kube-state-metrics / kubelet for **CPU limit (cores)**, **memory limit (bytes)**, and a **PVC capacity** proxy for the disk channel.
3. `norm_max[name] = max(capacity_max.get(name), observed_max[name])` with a small floor.

Training vectors are `z = 100 * (raw / norm_max)` per channel, i.e. values in **[0, 100]^D** when raw ≤ cap.

### Disk channel caveat (read the code comment)

`_capacity_norm_max()` maps PVC capacity into the **disk-throughput** slot of the same three-key normalization map in `main.py`. The inline comment there notes a **unit mismatch** between I/O rate and storage capacity; the field is still used as a **normalization divisor** for that channel. Operators should treat the disk channel as “stress proxy normalized by a capacity-derived scale,” not as a dimensionally pure bytes-per-second cap.

### Live inference

The same `norm_max` dict is frozen after training or loaded from snapshot. `_normalize_vector()` rebuilds the three-vector from the current sample and applies `100 * raw / denom` with `denom = max(norm_max[f], 1e-9)`.

## SOM class (exact update rule)

`class SOM` in `main.py`:

- **Lattice:** `rows` × `cols` neurons, each weight in **R^D** with **D = 3** (the three replica-averaged channels above).
- **Initialization:** uniform random weights in **[0, 100]^D** (same scale as normalized inputs).
- **BMU:** argmin of Euclidean distance `||w_{r,c} - z||_2` over the grid.
- **Neighborhood update:** for each training step, Gaussian kernel on **squared grid distance** to the BMU, multiplied by a **hard mask**: only cells with squared distance **≤ radius^2** are updated. Code uses `radius=2` (integer cell steps), and `SOM_SIGMA` in the exponent. Update: `w += lr * neighborhood * (z - w)` (vectorized over the lattice).
- **Training loop:** `train()` runs `TRAIN_EPOCHS` outer repeats; each epoch **shuffles** the dataset and calls `train_step` per sample.

### Area map (local roughness **A**)

After training, `area_map()` computes for each cell **(r, c)** the sum over **4-neighbors** (north, south, east, west only) of **L1 distance** between weight vectors: sum of `|w_{r,c} - w_{neighbor}|_1`. The scalar score for an observation is `**A[bmu_r, bmu_c]`** — the area value at the BMU, matching the report’s “geometric stress on the map” wording.

## Training pipeline (bootstrap and K-fold selection)

When no snapshot is loaded:

1. `_poll_loop` collects `Sample` objects until `_train()` sees at least `BOOTSTRAP_SAMPLES` **valid** samples.
2. `_train()` builds smoothed raw matrix, `norm_max`, normalized matrix `train_data_norm`.
3. **3-fold** `sklearn.model_selection.KFold` (`shuffle=True`, `random_state=42`) splits indices.
4. For each fold, a fresh `SOM` trains **only** on the fold’s training split for `TRAIN_EPOCHS`, builds `area_map`, scores validation vectors at their BMUs, and records `**sum_area`** = sum of validation BMU area values (lower is treated as better for that fold).
5. The fold with **minimum `sum_area`** wins; its `SOM` and `area_map` become `state.som` / `state.area_map`.
6. Fold diagnostics are stored on the state as `kfold_metrics` (surfaced in `/report` and optional `kfold_metrics` in `/export/som-snapshot`).

### Threshold **τ** (implementation detail vs report wording)

The report text describes setting **τ** from a high percentile of **scores on bootstrap data**. In code, after the best map is chosen, `_refresh_threshold()` sets:

`threshold = percentile( area_map.flatten(), THRESHOLD_PERCENTILE )`

So **τ** is the **P-th percentile of area values over all neurons** of the final map (default `THRESHOLD_PERCENTILE=85`), not the percentile of per-sample BMU scores on the training set. Operators should treat **τ** as a map-geometry cutoff tied to the chosen percentile hyperparameter; for ablations, retrain or reload snapshots when changing `THRESHOLD_PERCENTILE`.

## Live scoring, smoothing, streaks, and alarms

### UBL–NS vs UBL–5PtS (report names)

- **UBL–NS:** set `SMOOTH_K` to `1` (or equivalent) so `_moving_avg` returns the current normalized vector unchanged.
- **UBL–5PtS:** default `SMOOTH_K=5`; `_moving_avg` keeps a Python list history and returns the mean of the last **K** normalized vectors before BMU lookup.

Training uses `_apply_training_smoothing`, which applies the same trailing-window idea **along the training sample index order** (not wall-clock), so offline and online smoothing philosophies align.

### Scoring step (`_score_sample`)

1. Normalize; if `missing` is non-empty, drop (increments the missing-metrics drop counter in `main.py` when required per-pod keys are absent).
2. Apply moving average to produce **z'** (or **z** if K=1).
3. BMU + `area_value = area_map[bmu]`.
4. `is_anomaly = (area_value >= threshold)` (inclusive).
5. Streak: increments on anomaly else resets to 0.
6. **Causes:** `_cause_ranking` runs whenever `is_anomaly` is true for that tick (not only when an alarm fires), so the score stream can show `causes` on threshold-crossing polls before the streak reaches `ANOMALY_STREAK`.
7. **Online weight updates:** if `ONLINE_UPDATE_ENABLED` and `phase != "chaos"`, the code calls `som.train_step(vec)` and recomputes `area_map` every scored tick. Threshold **recalculation** after online updates exists in comments only (`THRESHOLD_RECALC_*` is not active in the current train_step path).

### Alarm emission

When `anomaly_streak >= ANOMALY_STREAK`, `_record_alarm` appends to the bounded `alarms` deque and increments demo Prometheus counters (`ubl_demo_event_*`) for external runbooks.

## Cause inference (`_cause_ranking`)

Post-hoc; **does not** change `area_value` or the streak logic.

Algorithm in code:

1. Iterate `radius = 1 .. max(rows, cols)`. For each value, scan the bounding square around the BMU but **keep only** cells whose **Manhattan** distance from the BMU satisfies `|r - bmu_r| + |c - bmu_c| <= radius` (nested L1 “diamonds”, growing with `radius`).
2. Collect grid cells where `**area_map[r,c] < threshold`** — treated as “normal-like” neighbors on the map.
3. Stop when `**CAUSE_Q**` such neighbors are collected or the grid is exhausted.
4. For each neighbor, compute channel-wise `abs(w_bmu - w_neighbor)`; vote for the feature name with the **largest** deviation on that neighbor (`feature_order` lists the same three channel names as the averaging list in `main.py`).
5. Return channel names sorted by vote count (`Counter.most_common()`), not raw magnitudes.

Interpretation matches the report caveats: **correlational** hints; aggregation across replicas can hide single-node hotspots.

## Phase tagging and reporting

Phases are exactly: `normal`, `load`, `chaos`, `cooldown` (`KNOWN_PHASES`). `POST /phase` sets `state.phase`; every score event includes `"phase"`.

`/report` aggregates counters, optional `kfold_metrics`, mean/median **lead time** heuristic: time from first `chaos` score-stream item to subsequent alarm timestamps (lab helper, not a substitute for formal evaluation windows in the report).

## `/score-stream` SLO enrichment (NoSQLBench)

Separate from infrastructure-metric scoring, when clients call `GET /score-stream`, the handler may attach:

- `p95_ms`, `p99_ms` from Prometheus `query_range` on `max(nosqlbench_histostat_p95_ms{tag="execute"})` (and p99), bucketed by `NB_SLO_STEP_SEC`.
- `slo_violated` when `p95_ms > NB_SLO_THRESHOLD_MS` (default 200).

`_NoSQLBenchSLOCache` deduplicates range queries with TTL `NB_SLO_CACHE_TTL_SEC` so large `limit` parameters do not stampede Prometheus.

## Prometheus metrics exposed by the learner

`GET /metrics` serves `prometheus_client` gauges/counters including:

- `ubl_ready`, `ubl_trained`, `ubl_alarm_count`
- `ubl_demo_event_total` and related gauges for scripted demo events

See `main.py` top-of-file metric definitions.

The HTTP process is `app.run(host="0.0.0.0", port=8100, threaded=True)` in `main.py`.

## Dependencies

From `ubl-learner/requirements.txt`:

- `flask`
- `numpy`
- `requests`
- `scikit-learn`
- `prometheus-client`

## Kubernetes Deployment

Apply learner manifests:

```bash
kubectl apply -f k8s/ubl-learner/ubl-learner-config.yaml
kubectl apply -f k8s/ubl-learner/ubl-learner-deployment.yaml
kubectl apply -f k8s/ubl-learner/ubl-learner-service.yaml
```

Default scheduling in the deployment is pinned to `control-node`.
Make sure this hostname exists in your cluster.

## Runtime API Surface

The report describes health, phase, score stream, alarms, metrics, and export paths. Exact routes in `main.py`:


| Method | Path                   | Role                                                               |
| ------ | ---------------------- | ------------------------------------------------------------------ |
| GET    | `/health`              | Liveness-style `{status: up}`                                      |
| GET    | `/status`              | Bootstrap counts, threshold, coverage, last missing keys           |
| POST   | `/phase`               | JSON `{"phase":"normal|load|chaos|cooldown"}`                      |
| GET    | `/score-stream?limit=` | Recent events; may add NB `p95_ms` / `p99_ms` / `slo_violated`     |
| GET    | `/alarms?limit=`       | Alarm deque tail                                                   |
| GET    | `/report`              | Aggregate run statistics                                           |
| GET    | `/metrics`             | Prometheus text                                                    |
| POST   | `/reset`               | Clears state; reloads snapshot from `UBL_SNAPSHOT_PATH` if present |
| GET    | `/export/som-snapshot` | JSON bundle of weights, area map, caps, threshold                  |
| GET    | `/config`              | Effective env-derived configuration summary                        |
| POST   | `/demo-event`          | Publishes demo counter metrics for automation                      |


## Learner Config

Key config values are in `k8s/ubl-learner/ubl-learner-config.yaml`:

- `PROMETHEUS_BASE`
- `TARGET_NAMESPACE`
- `CASSANDRA_PODS`
- `POLL_SEC`
- `BOOTSTRAP_SAMPLES`
- `SOM_ROWS`, `SOM_COLS`
- `THRESHOLD_PERCENTILE`
- `ANOMALY_STREAK`
- `SMOOTH_K`
- `UBL_SNAPSHOT_PATH`

Additional important controls in code/env:

- `SOM_LR`, `SOM_SIGMA`, `TRAIN_EPOCHS`
- `CAUSE_Q`
- `ONLINE_UPDATE_ENABLED`
- `THRESHOLD_RECALC_ENABLED`, `THRESHOLD_RECALC_EVERY_UPDATES` (wired in config; online recalc path largely commented in scoring hot path)
- `PROM_QUERY_TIMEOUT_SEC`, `PROM_QUERY_WORKERS`
- per-metric minimum pod coverage fraction (default **0.67**; see coverage env in `ubl-learner/main.py`)
- `MAX_SCORE_STREAM`, `MAX_ALARMS`
- `NB_SLO_THRESHOLD_MS`, `NB_SLO_STEP_SEC`, `NB_SLO_CACHE_TTL_SEC`

## Hyperparameter Guidance (Implementation-Oriented)

These controls directly affect runtime behavior:

- lattice size (`SOM_ROWS`, `SOM_COLS`): model capacity vs sample demand
- `SOM_LR`, `SOM_SIGMA`, `TRAIN_EPOCHS`: fit stability vs specialization (with K-fold picking among folds)
- threshold percentile: sensitivity of **τ** on the **area map** distribution
- anomaly streak: debounce strength vs detection delay
- smoothing window (`SMOOTH_K`): UBL–5PtS noise filtering vs lag
- cause list size (`CAUSE_Q`): neighbor count for voting
- minimum fraction of `CASSANDRA_PODS` that must return each base metric during churn (default **0.67**)

Use stable defaults first, then tune one parameter at a time.

## Snapshot JSON schema (online / offline contract)

`GET /export/som-snapshot` and `offline-training/train_offline_wout_no_of_samples.py` write compatible JSON. Required keys for **load** (`_apply_som_snapshot_unlocked`):

- `som_rows`, `som_cols`
- `feature_order` — must match the learner’s built-in three-entry list exactly or load fails (same strings as in `ubl-learner/main.py`)
- `norm_max` — object with all `feature_order` keys
- `threshold` — float **τ**
- `weights` — list shaped `[rows][cols][dims]`
- `area_map` — list shaped `[rows][cols]`

Optional: `threshold_percentile`, `training_duration_sec`, `kfold_metrics` on export.

`Dockerfile` copies `*.json` into `/models/`; default mount path in ConfigMap points to `som_trained_snapshot.json`.

## Local Health Check

With port-forward active:

```bash
curl -sS http://localhost:8100/health
curl -sS http://localhost:8100/status
```

## End-to-End Runtime Flow

1. `ubl-learner` starts and reads config/env.
2. If snapshot path resolves to a file, load weights, area map, caps, **τ**, mark trained.
3. Else learner pulls Prometheus metrics each poll until enough valid bootstrap samples exist, then runs `_train()`.
4. Live loop: collect → normalize → smooth → score → optional online `train_step` (non-chaos) → append score stream / alarms.
5. Score stream and alarms become available through HTTP; Grafana can scrape `/metrics`.

## Offline Training Workflow

Offline scripts are under `offline-training/`. They import `ubl-learner/main.py` as a module; `train_offline_wout_no_of_samples.py` stops the imported learner’s background thread so training is deterministic.

### 1) Collect samples

```bash
python3 offline-training/collect_prometheus_samples.py \
  --prometheus-base http://localhost:9090 \
  --duration-sec 180 \
  --output-json offline-training/artifacts/prometheus_samples.json
```

Collector `values` keys must match the live learner: each base metric string from `main.py`, suffixed with `__` and the pod name (same composite pattern the polling loop builds).

### 2) Train SOM snapshot

```bash
python3 offline-training/train_offline_wout_no_of_samples.py \
  --samples-json offline-training/artifacts/prometheus_samples.json \
  --output-dir offline-training/artifacts \
  --output-file som_trained_snapshot.json \
  --offline-mode
```

The script’s `--offline-mode` sets `state.offline_mode` on the minimal training harness (mainly for logging). **`LearnerState._train()` in `main.py` does not branch on that flag:** it still calls `_capacity_norm_max()`, which queries Prometheus for kube limits and PVC capacity when reachable. If those queries return nothing (for example no port-forward to Prometheus), `norm_max` effectively falls back to **observed training maxima** because `capacity_max.get(name, observed_max[name])` uses the bootstrap column maxima.

### 3) Train kNN snapshot (offline baseline)

```bash
python3 offline-training/train_knn_offline.py \
  --samples-json offline-training/artifacts/prometheus_samples.json \
  --output-dir offline-training/artifacts \
  --output-file knn_trained_snapshot.json
```

The kNN trainer builds reference vectors and a distance threshold **τ** for comparison. The online Flask learner in this repository **does not** load kNN snapshots; kNN is used by `run_offline_inference.py` and reporting-style comparisons.

### 4) Run offline inference

```bash
python3 offline-training/run_offline_inference.py \
  --samples-json offline-training/artifacts/prometheus_samples.json \
  --som-snapshot-5pts offline-training/artifacts/som_trained_snapshot.json \
  --knn-snapshot offline-training/artifacts/knn_trained_snapshot.json \
  --output offline-training/artifacts/offline_inference.json
```

That script scores each tick with both **UBL–NS** and **UBL–5PtS** semantics and kNN distances, using each snapshot’s own `norm_max` (matches training conditions).

## Offline and Online Snapshot Contract

The snapshot captures:

- SOM dimensions
- feature order (must match the live learner’s three-entry list in `main.py`)
- normalization caps
- threshold **τ**
- SOM weights
- area map

This contract is why offline-generated snapshots can be loaded by the online learner service.

## Snapshot Usage

The learner can load a trained SOM snapshot using `UBL_SNAPSHOT_PATH`.
The default deployment points to `/models/som_trained_snapshot.json` in the image.

If you train a new snapshot, update image contents or mount the file path and restart learner.

## Data Quality and Invalid Samples

The methodology states that invalid or missing critical samples should not be silently imputed.
In this implementation flow:

- missing required metric sets should be treated as invalid
- invalid samples should not drive training updates
- invalid samples should not produce normal scoring decisions

This prevents false structure in the SOM state.

## Artifacts

Common output locations:

- `offline-training/artifacts/prometheus_samples*.json`
- `offline-training/artifacts/som_trained_snapshot*.json`
- `offline-training/artifacts/knn_trained_snapshot*.json`
- `offline-training/artifacts/offline_inference*.json`

## Implementation Checklist

Before running integration tests:

1. confirm learner Deployment is Ready
2. confirm `PROMETHEUS_BASE` points to reachable Prometheus service
3. confirm `CASSANDRA_PODS` list matches running pod names
4. confirm threshold/streak/smoothing values are intentional
5. confirm health and status endpoints respond
6. confirm score stream and alarm endpoints return valid JSON

