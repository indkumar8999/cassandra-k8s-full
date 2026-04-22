# train_offline.py

Standalone offline SOM training script that imports from `main.py` and trains a Self-Organizing Map using metrics fetched directly from Prometheus.

## Features

- **Imports SOM class from main.py** — No code duplication
- **Fetches metrics from Prometheus** — Continuously polls for specified duration
- **K-fold Cross-Validation** — Trains 3 SOM models, selects best based on validation area
- **Saves JSON snapshot** — Compatible with `/import/som-snapshot` endpoint in learner
- **CLI interface** — Easy to run with custom parameters

## Usage

```bash
python3 train_offline.py \
  --prometheus-base http://10.152.34.58:9090 \
  --duration-sec 180 \
  --poll-interval 1.0 \
  --output-dir ./artifacts \
  --output-file som_trained_snapshot.json
```

## Parameters

| Argument | Default | Description |
|----------|---------|-------------|
| `--prometheus-base` | http://prometheus-operated.monitoring.svc.cluster.local:9090 | Prometheus server URL |
| `--duration-sec` | 180 | How long to collect metrics (seconds) |
| `--poll-interval` | 1.0 | Query interval (seconds) |
| `--output-dir` | ./artifacts | Directory for saved snapshot |
| `--output-file` | som_trained_snapshot.json | Output filename |

## Example: Train for 3 minutes

```bash
cd /mnt/ncsudrive/d/drank/cassandra-k8s-full/ubl-learner

python3 train_offline.py \
  --prometheus-base http://10.152.34.58:9090 \
  --duration-sec 180 \
  --poll-interval 1.0 \
  --output-dir ../artifacts
```

## Output

Saves a JSON snapshot file containing:
- `som_rows`, `som_cols` — Grid dimensions (32×32)
- `feature_order` — List of metric names (CPU, memory, disk I/O)
- `weights` — Trained SOM weight matrix
- `area_map` — Quantization error for each neuron
- `norm_max` — Normalization factors for each feature
- `threshold` — Anomaly detection threshold (85th percentile of area_map)

## Using the Snapshot

Import the trained snapshot into learner for inference (no retraining):

```bash
curl -X POST http://localhost:8100/import/som-snapshot \
  -H "Content-Type: application/json" \
  -d @../artifacts/som_trained_snapshot.json
```

Or run test with the snapshot:

```bash
export SOM_SNAPSHOT_PATH=../artifacts/som_trained_snapshot.json

python3 orchestrator/test_5_cpu_spike_test.py \
  --simulator-base http://localhost:8080 \
  --learner-base http://localhost:8100 \
  --chaos-base http://localhost:8200 \
  --som-snapshot-path "$SOM_SNAPSHOT_PATH"
```

## How It Works

1. **Collect** — Polls Prometheus for `duration-sec` seconds at `poll-interval` frequency
   - Fetches per-pod metrics: CPU usage, memory working set, disk I/O rates
   - Collects raw samples with metric__pod keys
2. **Normalize** — Averages metrics across pods, normalizes to 0-100 scale
3. **Train** — Performs 3-fold cross-validation
   - Each fold: trains SOM, evaluates on holdout validation set
   - Selects model with minimum sum of validation BMU areas
4. **Save** — Exports weights, area_map, and configuration to JSON

## Dependencies

- `numpy` — Array operations
- `sklearn` — K-fold cross-validation
- `requests` — HTTP queries to Prometheus
- `main.py` (same directory) — SOM class and config constants
