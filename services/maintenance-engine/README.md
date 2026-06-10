# RailOS Predictive Maintenance Engine

Advisory-only predictive maintenance inference service for Indian Railways (IR) rolling-stock
bearing and track component health. Satisfies **Requirement 4** and **Requirement 18** of the
RailOS Pilot System specification.

---

## Model Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MaintenanceLSTM  (Design §6.2)                       │
│                                                                         │
│  Input: (1, 1800, 8) float32                                            │
│         └── 30 min × 1 Hz = 1800 timesteps, 8 features per step        │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  LSTM layer 1  hidden=128  dropout=0.0 (deterministic, EN 50128) │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │                                          │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │  LSTM layer 2  hidden=128  dropout=0.0                           │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │  last timestep → h[-1]                  │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │  Dense(128 → 64)  ReLU                                           │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │                                          │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │  Dense(64 → 1)  Sigmoid                                          │   │
│  └───────────────────────────┬──────────────────────────────────────┘   │
│                              │                                          │
│             failure_probability ∈ [0.0, 1.0]                           │
└──────────────────────────────┼──────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│         ConformalMaintenanceWrapper  (Design §6.2, Req 4 C6–C7)         │
│                                                                         │
│  Symmetric conformal interval (90% nominal coverage):                  │
│    ci_lower = max(0, prob − q̂₉₀)                                       │
│    ci_upper = min(1, prob + q̂₉₀)                                       │
│                                                                         │
│  CI width rule  (p = interpolation_pct):                               │
│    width(p) ≥ width(0%) × (1 + p/20)  for p ∈ (0%, 40%]              │
│                                                                         │
│  interpolation_pct > 40% → insufficient_data = True, NaN scores        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Feature Mapping Table

| Index | Feature Name           | OMRS Field          | WILD Field              | Unit  |
|-------|------------------------|---------------------|-------------------------|-------|
| 0     | vibration_rms          | `bearing_rms_g`     | —                       | g     |
| 1     | vibration_kurtosis     | `bearing_kurtosis`  | —                       | —     |
| 2     | vibration_peak         | `bearing_peak_g`    | —                       | g     |
| 3     | temperature_bogie      | `bogie_temp_c`      | —                       | °C    |
| 4     | wheel_load_left        | —                   | `wheel_load_left_kn`    | kN    |
| 5     | wheel_load_right       | —                   | `wheel_load_right_kn`   | kN    |
| 6     | acoustic_emission_rms  | `acoustic_rms`      | —                       | V·rms |
| 7     | speed_kmh              | `speed_kmh`         | `speed_kmh`             | km/h  |

Missing fields default to `0.0` when not provided by a source.

---

## Service Components

```
services/maintenance-engine/
├── features/
│   └── feature_extractor.py   # Kafka consumer: OMRS+WILD → rolling window → features topic
├── model/
│   ├── lstm_model.py           # MaintenanceLSTM (2-layer, 128 hidden, deterministic)
│   └── conformal_wrapper.py    # ConformalMaintenanceWrapper (conformal CI, width rule)
├── service/
│   ├── shap_attribution.py     # Top-3 feature attribution via gradient × input / SHAP
│   └── maintenance_service.py  # FastAPI + Kafka consumer: inference, advisory emission
├── tests/
│   ├── conftest.py             # Fixtures: synthetic_feature_window, wrapped_model
│   └── test_benchmark.py       # Benchmark / property tests (Task 7.8)
├── 01-configmap.yaml           # Kubernetes ConfigMap
├── 02-deployment.yaml          # Kubernetes Deployment (2 replicas, UID 1000)
├── requirements.txt
└── README.md                   # This file
```

---

## Data Flow

```
train.telemetry.omrs  ──┐
                        ├─► feature_extractor.py ──► train.features.maintenance
train.telemetry.wild  ──┘        (30-min window)           │
                                                           ▼
                                                 maintenance_service.py
                                                 (LSTM inference + SHAP)
                                                           │
                                       ┌───────────────────┤
                                       ▼                   ▼
                               MAINTENANCE_ADVISORY  INSUFFICIENT_DATA
                               (prob > 0.80)         (interp > 40%)
                                       │
                               maintenance.advisories
```

---

## Requirement References

| Requirement | Criterion | Satisfied By |
|-------------|-----------|--------------|
| Req 4 C1    | 30-min rolling window → failure probability within 10 s of window boundary | `feature_extractor.py` + `maintenance_service.py` |
| Req 4 C2    | `MAINTENANCE_ADVISORY` emitted when prob > 0.80 | `maintenance_service.py` |
| Req 4 C3    | Deterministic inference (identical input → identical output) | `lstm_model.predict_deterministic()` |
| Req 4 C4    | Linear interpolation for gaps > 5 min; DATA_QUALITY flag | `feature_extractor.py` |
| Req 4 C5    | `INSUFFICIENT_DATA` emitted when interp_pct > 40%; no score field | `feature_extractor.py` + `maintenance_service.py` |
| Req 4 C6    | CI width ≥ width(0%) × (1 + p/20) for p ∈ (0%, 40%] | `conformal_wrapper.py` |
| Req 4 C7    | CI finite and non-zero for all valid inputs (interp ≤ 40%) | `conformal_wrapper.py` |
| Req 18      | SHAP top-3 feature attribution in advisory payload | `shap_attribution.py` |

---

## Running the Tests

```bash
# From the repo root
cd services/maintenance-engine
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

---

## Environment Variables (ConfigMap `maintenance-engine-config`)

| Variable                  | Default                                          | Description                                  |
|---------------------------|--------------------------------------------------|----------------------------------------------|
| `MODEL_PATH`              | `/models/maintenance_lstm_v1.0.0.pt`             | Path to serialised LSTM state-dict           |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka-cluster-kafka-bootstrap.railos:9092`      | Kafka broker list                            |
| `FAILURE_THRESHOLD`       | `0.80`                                           | Probability threshold for MAINTENANCE_ADVISORY |
| `MODEL_VERSION`           | `1.0.0`                                          | Semantic version logged in every advisory    |
| `PROMETHEUS_PORT`         | `9090`                                           | Port for Prometheus metrics scrape endpoint  |
| `HORIZON_HOURS`           | `72`                                             | Forecast horizon in every advisory           |
| `LOG_LEVEL`               | `INFO`                                           | Python logging level                         |
