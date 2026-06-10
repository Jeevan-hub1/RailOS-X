<<<<<<< HEAD
# RailOS — Cognitive Operating System for Indian Railways

> **A corridor-scale, infrastructure-grade cognitive railway operating system** — integrating real-time
> sensor pipelines, edge AI, federated learning, multi-agent scheduling, a digital twin, and IEC 62443
> cybersecurity — scoped to a single pilot corridor on Indian Railways.

---

## What Is RailOS?

Most railway AI projects build object detection, prediction dashboards, or isolated optimization modules.

RailOS is different. It is a **railway operating ecosystem** — a unified cognitive layer that connects
safety, AI, observability, governance, edge autonomy, cybersecurity, human oversight, failover, digital
twin state, and the full ML lifecycle into one coherent architecture.

This is not a feature. It is an operating system for a railway corridor.

```
"The core insight — that Indian Railways needs unified intelligence
 rather than isolated optimization modules — is correct and worth pursuing."
                          — Deep Research Report, June 2026
```

---

## Architecture in One Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TIER 4 — CENTRAL CORE                           │
│  Kafka (RF=3) · InfluxDB · MLflow · Prometheus · Kong · Keycloak    │
│  Digital Twin State Store · OpenTelemetry · Vault · MinIO WORM       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ FRMCS 5G mIoT / LTE-R
┌───────────────────────────▼─────────────────────────────────────────┐
│                    TIER 3 — ZONE COMPUTE                            │
│  FL Aggregator (Flower) · HetGNN Delay Predictor · DT Sync          │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ FRMCS 5G / LTE-R
┌───────────────────────────▼─────────────────────────────────────────┐
│              TIER 2 — STATION EDGE NODES (Jetson Orin)              │
│  YOLOv8 Defect Detector · LSTM Predictive Maintenance               │
│  Heartbeat FSM · 24h Local Buffer · Hardware Telemetry              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ MQTT / CoAP
┌───────────────────────────▼─────────────────────────────────────────┐
│                   TIER 1 — MICRO-EDGE SENSORS                       │
│  Vibration (MEMS) · GPS · Temperature · Cameras · RFID              │
└─────────────────────────────────────────────────────────────────────┘

IEC 62443 Security Zones:
  Zone 1 (Business) ↔ conduit ↔ Zone 2 (RailOS) ↔ conduit ↔ Zone 3 (SCADA)
                                                   ↕ DATA DIODE (hardware)
                                                   Zone 4 (Kavach / SIL-4)
```

---

## Core Subsystems

| Subsystem | Technology | What It Does |
|-----------|-----------|--------------|
| **Real-Time Data Pipeline** | Kafka · Flink · InfluxDB 3.0 | Ingests sensor events from OMRS, WILD, GPS, vibration, cameras at ≥10,000 events/s |
| **Track Defect Detector** | YOLOv8n · TensorRT INT8 · Grad-CAM | Detects rail cracks, flaking, fastener issues from trackside cameras in 100ms on Jetson Orin |
| **Predictive Maintenance Engine** | LSTM/GRU · MAPIE conformal CI · SHAP | Forecasts bearing/track failure probability over 72-hour horizon with calibrated confidence intervals |
| **Delay Predictor** | HetGNN (GraphSAGE) · conformal PI | Predicts train delay propagation across corridor graph in 2s; 90% prediction intervals |
| **Federated Learning Layer** | Flower (flwr) · Opacus DP | Shares model improvements across 5+ zone edge nodes with differential privacy — no raw data leaves the edge |
| **MARL Train Scheduler** | Flatland-RL · PPO (SB3) | Proposes conflict-free rescheduling plans within 30s of disruption detection |
| **Digital Twin** | Three.js · Deck.gl · PostGIS · OpenTrack | Live GIS visualization distinguishing confirmed, predicted, simulated, and stale states with uncertainty bands |
| **Cybersecurity Dashboard** | LSTM Autoencoder · Grafana · MinIO WORM | Monitors SCADA traffic for anomalies; captures forensic evidence to WORM storage on every alert |
| **Kavach++ Advisory Layer** | Physics braking model · 1D-CNN adhesion | Read-only ML advisory overlay on Kavach 4.0 — never modifies certified safety logic, always more conservative |
| **Human Authorization Gate** | Structural boundary | No advisory reaches any operational system without explicit OC authorization — non-configurable, non-bypassable |

---

## What Makes This Different

Most railway AI:
- Object detection
- Prediction dashboards
- Isolated APIs

RailOS adds:

| Capability | Implementation |
|-----------|---------------|
| **Isolation zones** | IEC 62443 Zone 1–4 with hardware data diode at Zone 3/4 boundary |
| **Data diode architecture** | Hardware-enforced one-way read from Kavach — zero write path from any software |
| **Formal invariants** | 7 property-based tests (Hypothesis): conflict-free MARL, Kavach conservatism, FL quality bound, CI monotonicity |
| **Explainability** | Grad-CAM overlays + SHAP top-3 features in IR domain language on every advisory |
| **Drift detection** | Evidently AI PSI daily rolling window; DRIFT_WARNING surfaced to operators |
| **Forensic storage** | MinIO Object Lock WORM; raw 60s SCADA capture + reconstruction error on every anomaly |
| **Supply chain security** | cosign signatures, Syft SBOM (CycloneDX), Grype CVE scanning, NVD feed polling |
| **Traceability matrix** | Every requirement linked to hazards, mitigations, evidence, and deployed model version |
| **Hazard register** | PostgreSQL append-only; HAZARD_REVIEW_REQUIRED triggered by anomaly pattern detection |
| **Failover architecture** | Kafka RF=3, InfluxDB hot standby, PostgreSQL Patroni HA, 24h edge autonomous operation |
| **Autonomous edge inference** | Edge_Nodes continue locally on disconnect; circular buffer, cold-restart capable |
| **FRMCS slicing** | URLLC (<1ms) for safety, eMBB for video, mIoT for sensors on same physical infrastructure |
| **Federated learning governance** | DVC dataset versioning + Fairlearn + ART adversarial validation as CI/CD blocking gates |

---

## Pilot Scope vs Full Vision

| Module | Pilot Implementation | Full Vision |
|--------|---------------------|-------------|
| Digital Twin | ✅ Live GIS + real-time state + visual encoding | National-scale 68,000km |
| Kafka pipeline | ✅ Full Kafka/Flink/InfluxDB on pilot corridor | 50M events/s at national scale |
| Defect detection | ✅ YOLOv8 on edge hardware | All 68,000km of track |
| Delay prediction | ✅ HetGNN on NTES data | All 13,000 daily trains |
| Human auth gate | ✅ Structural gate, risk tiers, dual-auth | Same — regulatory requirement |
| Observability | ✅ Prometheus + OTel + ELK | Same stack, scaled |
| Cyber anomaly | ✅ LSTM autoencoder, simulated SCADA | Real SCADA integration |
| Federated learning | ⚠️ Simulated 5 zone clients | Real 8,000+ edge nodes |
| MARL scheduler | ⚠️ Flatland-RL simplified topology | 13,000 agents, full IR network |
| Kavach++ | ⚠️ Physics simulation, no live Kavach tap | Live Kavach 4.0 data bus read |
| 6G communication | ❌ Not in scope (2035+ horizon) | FRMCS 5G SA is the right standard now |
| National scale | ❌ Not in scope | 15-20 year engineering programme |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Edge compute** | NVIDIA Jetson Orin NX 16GB / AGX Orin |
| **Edge inference** | TensorRT INT8 (YOLOv8), TF Lite (LSTM fallback) |
| **Communication** | FRMCS 5G-Advanced (URLLC/eMBB/mIoT), LTE-R fallback |
| **Time sync** | PTP IEEE 1588, GPS-disciplined grandmaster, ±100ms max drift |
| **Event streaming** | Apache Kafka 3.x (3 brokers, RF=3) |
| **Stream processing** | Apache Flink |
| **Time-series DB** | InfluxDB 3.0 (primary + hot standby) |
| **Historical store** | Apache Delta Lake (Parquet) |
| **ML framework** | PyTorch 2.x, PyTorch Geometric (GNN), Stable Baselines3 (RL) |
| **Federated learning** | Flower (flwr) + Opacus (differential privacy) |
| **Explainability** | SHAP, Grad-CAM |
| **Model registry** | MLflow (MAJOR.MINOR.PATCH versioning) |
| **Drift detection** | Evidently AI (Population Stability Index) |
| **Fairness evaluation** | Fairlearn |
| **Adversarial testing** | ART (Adversarial Robustness Toolbox) |
| **Dataset versioning** | DVC |
| **Digital Twin viz** | Three.js + Deck.gl + React |
| **Geospatial** | PostGIS (PostgreSQL + spatial) |
| **Physics simulation** | OpenTrack + SimPy |
| **Identity & RBAC** | Keycloak (OIDC, TOTP MFA) |
| **API gateway** | Kong Gateway (JWT, rate limiting, versioning) |
| **Container security** | Kubernetes PSA restricted + Falco |
| **Supply chain** | cosign + Syft + Grype |
| **Forensic storage** | MinIO Object Lock (WORM) |
| **Observability** | Prometheus + Grafana + OpenTelemetry + Jaeger + ELK |
| **Config/secrets** | HashiCorp Vault (immutable audit log) |
| **Database HA** | PostgreSQL + Patroni |
| **PBT framework** | Hypothesis |
| **Operator UI** | React + Three.js + Deck.gl (WCAG 2.1 AA) |

---

## Implementation Phases

### Phase 1 — Core Infrastructure (Wave 1–4)
Build the data layer everything else depends on:
- Kafka cluster, InfluxDB, PostgreSQL Patroni HA, Flink
- Keycloak RBAC + MFA, Kong API gateway, HashiCorp Vault
- MinIO WORM, Prometheus + Grafana + OpenTelemetry + Jaeger + ELK
- PTP time synchronization
- NTES, OMRS, WILD legacy adapters
- Kafka topic hierarchy + Flink pipeline + schema validator

### Phase 2 — AI Subsystems (Wave 5–6)
Build all ML inference services in parallel:
- YOLOv8n defect detector (INT8 TensorRT, Grad-CAM, SHAP)
- LSTM/GRU predictive maintenance (conformal CI, INSUFFICIENT_DATA path)
- HetGNN delay predictor (conformal PI, REST endpoint)
- Flatland-RL MARL scheduler (PPO, conflict-free constraint layer)
- Kavach++ advisory layer (physics model, Zone 2 isolation)
- LSTM autoencoder cybersecurity + Grafana dashboard

### Phase 3 — Operations Layer (Wave 7–8)
Connect AI to operators:
- Digital Twin (PostGIS, InfluxDB state store, Three.js + Deck.gl, visual encoding)
- Human-in-the-loop authorization gate (risk tiers, dual-auth, audit log)
- Federated learning (Flower, Opacus DP, round protocol)
- Model governance CI/CD (MLflow, benchmark gate, Fairlearn, Evidently, ART, DVC)
- Safety compliance (traceability matrix, hazard register, Vault config versioning)

### Phase 4 — Validation and Hardening (Wave 9)
Prove it works:
- Operator UI (React, WCAG 2.1 AA, alert fatigue management)
- Property-based tests (7 Hypothesis invariants)
- Simulation validation (Digital Twin vs 30-day historical IR data, MARL on 100 scenarios)
- Red-team adversarial testing (SCADA injection, ART FGSM)
- Data retention lifecycle (archive/purge CronJob, forensic holds, monthly compliance report)
- Geographic failure isolation verification

---

## Spec Documents

| Document | Description |
|----------|-------------|
| [`.kiro/specs/railos-pilot-system/requirements.md`](.kiro/specs/railos-pilot-system/requirements.md) | 45 requirements — functional, safety, security, governance, and operator experience |
| [`.kiro/specs/railos-pilot-system/design.md`](.kiro/specs/railos-pilot-system/design.md) | Full architecture design — tier diagram, IEC 62443 zones, all ML subsystems, data schemas, PBTs |
| [`.kiro/specs/railos-pilot-system/tasks.md`](.kiro/specs/railos-pilot-system/tasks.md) | 130+ implementation tasks in 9 dependency waves |

---

## Key Design Decisions

**Why not 6G?** 6G standards are in study phase (3GPP Release 19–20). Commercial deployment in India is
realistically 2035+. FRMCS 5G-Advanced delivers every capability described in the RailOS concept today.
The "6G-X" label in the original hackathon concept is premature by a decade.

**Why advisory-only for Kavach?** Kavach 4.0 is SIL-4 certified (probability of dangerous failure
< 10⁻⁹/hour). Any modification to its safety logic requires RDSO recertification — a multi-year process.
The Kavach++ layer is read-only, deployed in Zone 2, with a hardware data diode enforcing the boundary.
This is the correct architecture for a research advisory layer.

**Why federated learning, not centralized training?** Indian Railways generates ~65 GB/s of raw sensor
data across 13,000 daily trains. Centralizing raw data is cost-prohibitive and violates data locality
requirements. FL with Opacus differential privacy shares only weight gradients (not raw data), handles
non-IID data across India's diverse climatic regions, and satisfies regulatory data governance.

**Why property-based testing for safety invariants?** Deterministic unit tests cannot cover the space
of possible disruption inputs for MARL or track conditions for Kavach advisory. Hypothesis generates
thousands of random inputs to verify that conflict-free proposals and braking curve conservatism hold
universally — not just for the test cases an engineer thought to write.

---

## Correctness Properties (Property-Based Tests)

Seven formally defined invariants, all implemented with Hypothesis:

| Property | Invariant | Requirement |
|----------|-----------|-------------|
| 1 | Every MARL proposal is Conflict-free | Req 7.2 |
| 2 | Kavach advisory stopping distance ≥ certified curve | Req 10.3 |
| 3 | FL global model ≤ worst local model validation loss | Req 6.2 |
| 4 | Confidence interval widens monotonically with interpolation rate | Req 4.6 |
| 5 | Risk score always in [0.0, 4.0] | Req 40.1 |
| 6 | No advisory reaches downstream without authorization record | Req 12.1, 30.1 |
| 7 | Delay predictor MAE increase ≤15% when training data drops 12mo→3mo | Req 5.4 |

---

## Compliance and Standards

| Standard | Application in RailOS |
|----------|----------------------|
| **EN 50128** | Railway software safety — deterministic inference (no stochastic layers at runtime), fixed-point quantization, version control |
| **IEC 62443** | OT cybersecurity — Zone 1–4 model, monitored conduits, data diode, SL4 for Zone 4 |
| **WCAG 2.1 AA** | Operator dashboard — color contrast, text sizing, keyboard navigability, high-contrast mode |
| **PTP IEEE 1588** | Time synchronization — ±100ms max drift from UTC across all subsystems |
| **CycloneDX / SPDX** | Software Bill of Materials for every deployment release |
| **OAuth 2.0 / JWT** | All API authentication |

---

## Research Context

RailOS is grounded in real research and real deployments:

- **Flatland-RL** (SBB/AICrowd, NeurIPS 2020) — the MARL simulation environment
- **HetGNN-SAGE** (Applied Soft Computing 2024) — the delay prediction architecture
- **YOLOv8 track defect detection** (MDPI 2025, ScienceDirect 2025) — 90%+ precision/recall on rail surface defects
- **Federated learning for railway point machines** (Zhang et al. 2024) — the FL architecture pattern
- **FRMCS / 3GPP** — the actual 5G railway communication standard replacing GSM-R
- **Delhi-Meerut RRTS digital twin** — the closest real-world precedent (82km corridor)
- **Kavach 4.0** (RDSO, 2024) — the real ATP system this advisory layer reads from

---

## Honest Feasibility Assessment

| Component | Technology Readiness | Pilot Timeline |
|-----------|---------------------|----------------|
| Kafka pipeline + edge nodes | TRL 9 (deployed globally) | 3–6 months |
| YOLOv8 defect detection | TRL 7–8 (near-deployment) | 6–12 months (data labeling first) |
| GNN delay prediction | TRL 4–5 (research→prototype) | 12–24 months |
| Federated learning | TRL 5–6 (research→pilot) | 12–18 months |
| MARL scheduling | TRL 3–4 (lab/simulation) | 24–36 months |
| Digital Twin (corridor level) | TRL 7–8 (proven by RRTS) | 12–18 months |
| Kavach++ advisory | TRL 3 (research) | 36–48 months (incl. RDSO review) |

**National scale**: 15–20 year engineering and institutional programme. This pilot demonstrates what unified corridor intelligence looks like at tractable scale.

---

## License

This project is for research and demonstration purposes. All safety-critical components are advisory-only
and must not be deployed in live railway operations without appropriate certification processes.

---

*Built on real algorithms. Grounded in real constraints. Designed for real railways.*
=======
# RailOS — Cognitive Operating System for Indian Railways

> **A corridor-scale, infrastructure-grade cognitive railway operating system** — integrating real-time
> sensor pipelines, edge AI, federated learning, multi-agent scheduling, a digital twin, and IEC 62443
> cybersecurity — scoped to a single pilot corridor on Indian Railways.

---

## What Is RailOS?

Most railway AI projects build object detection, prediction dashboards, or isolated optimization modules.

RailOS is different. It is a **railway operating ecosystem** — a unified cognitive layer that connects
safety, AI, observability, governance, edge autonomy, cybersecurity, human oversight, failover, digital
twin state, and the full ML lifecycle into one coherent architecture.

This is not a feature. It is an operating system for a railway corridor.

```
"The core insight — that Indian Railways needs unified intelligence
 rather than isolated optimization modules — is correct and worth pursuing."
                          — Deep Research Report, June 2026
```

---

## Architecture in One Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TIER 4 — CENTRAL CORE                           │
│  Kafka (RF=3) · InfluxDB · MLflow · Prometheus · Kong · Keycloak    │
│  Digital Twin State Store · OpenTelemetry · Vault · MinIO WORM       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ FRMCS 5G mIoT / LTE-R
┌───────────────────────────▼─────────────────────────────────────────┐
│                    TIER 3 — ZONE COMPUTE                            │
│  FL Aggregator (Flower) · HetGNN Delay Predictor · DT Sync          │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ FRMCS 5G / LTE-R
┌───────────────────────────▼─────────────────────────────────────────┐
│              TIER 2 — STATION EDGE NODES (Jetson Orin)              │
│  YOLOv8 Defect Detector · LSTM Predictive Maintenance               │
│  Heartbeat FSM · 24h Local Buffer · Hardware Telemetry              │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ MQTT / CoAP
┌───────────────────────────▼─────────────────────────────────────────┐
│                   TIER 1 — MICRO-EDGE SENSORS                       │
│  Vibration (MEMS) · GPS · Temperature · Cameras · RFID              │
└─────────────────────────────────────────────────────────────────────┘

IEC 62443 Security Zones:
  Zone 1 (Business) ↔ conduit ↔ Zone 2 (RailOS) ↔ conduit ↔ Zone 3 (SCADA)
                                                   ↕ DATA DIODE (hardware)
                                                   Zone 4 (Kavach / SIL-4)
```

---

## Core Subsystems

| Subsystem | Technology | What It Does |
|-----------|-----------|--------------|
| **Real-Time Data Pipeline** | Kafka · Flink · InfluxDB 3.0 | Ingests sensor events from OMRS, WILD, GPS, vibration, cameras at ≥10,000 events/s |
| **Track Defect Detector** | YOLOv8n · TensorRT INT8 · Grad-CAM | Detects rail cracks, flaking, fastener issues from trackside cameras in 100ms on Jetson Orin |
| **Predictive Maintenance Engine** | LSTM/GRU · MAPIE conformal CI · SHAP | Forecasts bearing/track failure probability over 72-hour horizon with calibrated confidence intervals |
| **Delay Predictor** | HetGNN (GraphSAGE) · conformal PI | Predicts train delay propagation across corridor graph in 2s; 90% prediction intervals |
| **Federated Learning Layer** | Flower (flwr) · Opacus DP | Shares model improvements across 5+ zone edge nodes with differential privacy — no raw data leaves the edge |
| **MARL Train Scheduler** | Flatland-RL · PPO (SB3) | Proposes conflict-free rescheduling plans within 30s of disruption detection |
| **Digital Twin** | Three.js · Deck.gl · PostGIS · OpenTrack | Live GIS visualization distinguishing confirmed, predicted, simulated, and stale states with uncertainty bands |
| **Cybersecurity Dashboard** | LSTM Autoencoder · Grafana · MinIO WORM | Monitors SCADA traffic for anomalies; captures forensic evidence to WORM storage on every alert |
| **Kavach++ Advisory Layer** | Physics braking model · 1D-CNN adhesion | Read-only ML advisory overlay on Kavach 4.0 — never modifies certified safety logic, always more conservative |
| **Human Authorization Gate** | Structural boundary | No advisory reaches any operational system without explicit OC authorization — non-configurable, non-bypassable |

---

## What Makes This Different

Most railway AI:
- Object detection
- Prediction dashboards
- Isolated APIs

RailOS adds:

| Capability | Implementation |
|-----------|---------------|
| **Isolation zones** | IEC 62443 Zone 1–4 with hardware data diode at Zone 3/4 boundary |
| **Data diode architecture** | Hardware-enforced one-way read from Kavach — zero write path from any software |
| **Formal invariants** | 7 property-based tests (Hypothesis): conflict-free MARL, Kavach conservatism, FL quality bound, CI monotonicity |
| **Explainability** | Grad-CAM overlays + SHAP top-3 features in IR domain language on every advisory |
| **Drift detection** | Evidently AI PSI daily rolling window; DRIFT_WARNING surfaced to operators |
| **Forensic storage** | MinIO Object Lock WORM; raw 60s SCADA capture + reconstruction error on every anomaly |
| **Supply chain security** | cosign signatures, Syft SBOM (CycloneDX), Grype CVE scanning, NVD feed polling |
| **Traceability matrix** | Every requirement linked to hazards, mitigations, evidence, and deployed model version |
| **Hazard register** | PostgreSQL append-only; HAZARD_REVIEW_REQUIRED triggered by anomaly pattern detection |
| **Failover architecture** | Kafka RF=3, InfluxDB hot standby, PostgreSQL Patroni HA, 24h edge autonomous operation |
| **Autonomous edge inference** | Edge_Nodes continue locally on disconnect; circular buffer, cold-restart capable |
| **FRMCS slicing** | URLLC (<1ms) for safety, eMBB for video, mIoT for sensors on same physical infrastructure |
| **Federated learning governance** | DVC dataset versioning + Fairlearn + ART adversarial validation as CI/CD blocking gates |

---

## Pilot Scope vs Full Vision

| Module | Pilot Implementation | Full Vision |
|--------|---------------------|-------------|
| Digital Twin | ✅ Live GIS + real-time state + visual encoding | National-scale 68,000km |
| Kafka pipeline | ✅ Full Kafka/Flink/InfluxDB on pilot corridor | 50M events/s at national scale |
| Defect detection | ✅ YOLOv8 on edge hardware | All 68,000km of track |
| Delay prediction | ✅ HetGNN on NTES data | All 13,000 daily trains |
| Human auth gate | ✅ Structural gate, risk tiers, dual-auth | Same — regulatory requirement |
| Observability | ✅ Prometheus + OTel + ELK | Same stack, scaled |
| Cyber anomaly | ✅ LSTM autoencoder, simulated SCADA | Real SCADA integration |
| Federated learning | ⚠️ Simulated 5 zone clients | Real 8,000+ edge nodes |
| MARL scheduler | ⚠️ Flatland-RL simplified topology | 13,000 agents, full IR network |
| Kavach++ | ⚠️ Physics simulation, no live Kavach tap | Live Kavach 4.0 data bus read |
| 6G communication | ❌ Not in scope (2035+ horizon) | FRMCS 5G SA is the right standard now |
| National scale | ❌ Not in scope | 15-20 year engineering programme |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Edge compute** | NVIDIA Jetson Orin NX 16GB / AGX Orin |
| **Edge inference** | TensorRT INT8 (YOLOv8), TF Lite (LSTM fallback) |
| **Communication** | FRMCS 5G-Advanced (URLLC/eMBB/mIoT), LTE-R fallback |
| **Time sync** | PTP IEEE 1588, GPS-disciplined grandmaster, ±100ms max drift |
| **Event streaming** | Apache Kafka 3.x (3 brokers, RF=3) |
| **Stream processing** | Apache Flink |
| **Time-series DB** | InfluxDB 3.0 (primary + hot standby) |
| **Historical store** | Apache Delta Lake (Parquet) |
| **ML framework** | PyTorch 2.x, PyTorch Geometric (GNN), Stable Baselines3 (RL) |
| **Federated learning** | Flower (flwr) + Opacus (differential privacy) |
| **Explainability** | SHAP, Grad-CAM |
| **Model registry** | MLflow (MAJOR.MINOR.PATCH versioning) |
| **Drift detection** | Evidently AI (Population Stability Index) |
| **Fairness evaluation** | Fairlearn |
| **Adversarial testing** | ART (Adversarial Robustness Toolbox) |
| **Dataset versioning** | DVC |
| **Digital Twin viz** | Three.js + Deck.gl + React |
| **Geospatial** | PostGIS (PostgreSQL + spatial) |
| **Physics simulation** | OpenTrack + SimPy |
| **Identity & RBAC** | Keycloak (OIDC, TOTP MFA) |
| **API gateway** | Kong Gateway (JWT, rate limiting, versioning) |
| **Container security** | Kubernetes PSA restricted + Falco |
| **Supply chain** | cosign + Syft + Grype |
| **Forensic storage** | MinIO Object Lock (WORM) |
| **Observability** | Prometheus + Grafana + OpenTelemetry + Jaeger + ELK |
| **Config/secrets** | HashiCorp Vault (immutable audit log) |
| **Database HA** | PostgreSQL + Patroni |
| **PBT framework** | Hypothesis |
| **Operator UI** | React + Three.js + Deck.gl (WCAG 2.1 AA) |

---

## Implementation Phases

### Phase 1 — Core Infrastructure (Wave 1–4)
Build the data layer everything else depends on:
- Kafka cluster, InfluxDB, PostgreSQL Patroni HA, Flink
- Keycloak RBAC + MFA, Kong API gateway, HashiCorp Vault
- MinIO WORM, Prometheus + Grafana + OpenTelemetry + Jaeger + ELK
- PTP time synchronization
- NTES, OMRS, WILD legacy adapters
- Kafka topic hierarchy + Flink pipeline + schema validator

### Phase 2 — AI Subsystems (Wave 5–6)
Build all ML inference services in parallel:
- YOLOv8n defect detector (INT8 TensorRT, Grad-CAM, SHAP)
- LSTM/GRU predictive maintenance (conformal CI, INSUFFICIENT_DATA path)
- HetGNN delay predictor (conformal PI, REST endpoint)
- Flatland-RL MARL scheduler (PPO, conflict-free constraint layer)
- Kavach++ advisory layer (physics model, Zone 2 isolation)
- LSTM autoencoder cybersecurity + Grafana dashboard

### Phase 3 — Operations Layer (Wave 7–8)
Connect AI to operators:
- Digital Twin (PostGIS, InfluxDB state store, Three.js + Deck.gl, visual encoding)
- Human-in-the-loop authorization gate (risk tiers, dual-auth, audit log)
- Federated learning (Flower, Opacus DP, round protocol)
- Model governance CI/CD (MLflow, benchmark gate, Fairlearn, Evidently, ART, DVC)
- Safety compliance (traceability matrix, hazard register, Vault config versioning)

### Phase 4 — Validation and Hardening (Wave 9)
Prove it works:
- Operator UI (React, WCAG 2.1 AA, alert fatigue management)
- Property-based tests (7 Hypothesis invariants)
- Simulation validation (Digital Twin vs 30-day historical IR data, MARL on 100 scenarios)
- Red-team adversarial testing (SCADA injection, ART FGSM)
- Data retention lifecycle (archive/purge CronJob, forensic holds, monthly compliance report)
- Geographic failure isolation verification

---

## Spec Documents

| Document | Description |
|----------|-------------|
| [`.kiro/specs/railos-pilot-system/requirements.md`](.kiro/specs/railos-pilot-system/requirements.md) | 45 requirements — functional, safety, security, governance, and operator experience |
| [`.kiro/specs/railos-pilot-system/design.md`](.kiro/specs/railos-pilot-system/design.md) | Full architecture design — tier diagram, IEC 62443 zones, all ML subsystems, data schemas, PBTs |
| [`.kiro/specs/railos-pilot-system/tasks.md`](.kiro/specs/railos-pilot-system/tasks.md) | 130+ implementation tasks in 9 dependency waves |

---

## Key Design Decisions

**Why not 6G?** 6G standards are in study phase (3GPP Release 19–20). Commercial deployment in India is
realistically 2035+. FRMCS 5G-Advanced delivers every capability described in the RailOS concept today.
The "6G-X" label in the original hackathon concept is premature by a decade.

**Why advisory-only for Kavach?** Kavach 4.0 is SIL-4 certified (probability of dangerous failure
< 10⁻⁹/hour). Any modification to its safety logic requires RDSO recertification — a multi-year process.
The Kavach++ layer is read-only, deployed in Zone 2, with a hardware data diode enforcing the boundary.
This is the correct architecture for a research advisory layer.

**Why federated learning, not centralized training?** Indian Railways generates ~65 GB/s of raw sensor
data across 13,000 daily trains. Centralizing raw data is cost-prohibitive and violates data locality
requirements. FL with Opacus differential privacy shares only weight gradients (not raw data), handles
non-IID data across India's diverse climatic regions, and satisfies regulatory data governance.

**Why property-based testing for safety invariants?** Deterministic unit tests cannot cover the space
of possible disruption inputs for MARL or track conditions for Kavach advisory. Hypothesis generates
thousands of random inputs to verify that conflict-free proposals and braking curve conservatism hold
universally — not just for the test cases an engineer thought to write.

---

## Correctness Properties (Property-Based Tests)

Seven formally defined invariants, all implemented with Hypothesis:

| Property | Invariant | Requirement |
|----------|-----------|-------------|
| 1 | Every MARL proposal is Conflict-free | Req 7.2 |
| 2 | Kavach advisory stopping distance ≥ certified curve | Req 10.3 |
| 3 | FL global model ≤ worst local model validation loss | Req 6.2 |
| 4 | Confidence interval widens monotonically with interpolation rate | Req 4.6 |
| 5 | Risk score always in [0.0, 4.0] | Req 40.1 |
| 6 | No advisory reaches downstream without authorization record | Req 12.1, 30.1 |
| 7 | Delay predictor MAE increase ≤15% when training data drops 12mo→3mo | Req 5.4 |

---

## Compliance and Standards

| Standard | Application in RailOS |
|----------|----------------------|
| **EN 50128** | Railway software safety — deterministic inference (no stochastic layers at runtime), fixed-point quantization, version control |
| **IEC 62443** | OT cybersecurity — Zone 1–4 model, monitored conduits, data diode, SL4 for Zone 4 |
| **WCAG 2.1 AA** | Operator dashboard — color contrast, text sizing, keyboard navigability, high-contrast mode |
| **PTP IEEE 1588** | Time synchronization — ±100ms max drift from UTC across all subsystems |
| **CycloneDX / SPDX** | Software Bill of Materials for every deployment release |
| **OAuth 2.0 / JWT** | All API authentication |

---

## Research Context

RailOS is grounded in real research and real deployments:

- **Flatland-RL** (SBB/AICrowd, NeurIPS 2020) — the MARL simulation environment
- **HetGNN-SAGE** (Applied Soft Computing 2024) — the delay prediction architecture
- **YOLOv8 track defect detection** (MDPI 2025, ScienceDirect 2025) — 90%+ precision/recall on rail surface defects
- **Federated learning for railway point machines** (Zhang et al. 2024) — the FL architecture pattern
- **FRMCS / 3GPP** — the actual 5G railway communication standard replacing GSM-R
- **Delhi-Meerut RRTS digital twin** — the closest real-world precedent (82km corridor)
- **Kavach 4.0** (RDSO, 2024) — the real ATP system this advisory layer reads from

---

## Honest Feasibility Assessment

| Component | Technology Readiness | Pilot Timeline |
|-----------|---------------------|----------------|
| Kafka pipeline + edge nodes | TRL 9 (deployed globally) | 3–6 months |
| YOLOv8 defect detection | TRL 7–8 (near-deployment) | 6–12 months (data labeling first) |
| GNN delay prediction | TRL 4–5 (research→prototype) | 12–24 months |
| Federated learning | TRL 5–6 (research→pilot) | 12–18 months |
| MARL scheduling | TRL 3–4 (lab/simulation) | 24–36 months |
| Digital Twin (corridor level) | TRL 7–8 (proven by RRTS) | 12–18 months |
| Kavach++ advisory | TRL 3 (research) | 36–48 months (incl. RDSO review) |

**National scale**: 15–20 year engineering and institutional programme. This pilot demonstrates what unified corridor intelligence looks like at tractable scale.

---

## License

This project is for research and demonstration purposes. All safety-critical components are advisory-only
and must not be deployed in live railway operations without appropriate certification processes.

---

*Built on real algorithms. Grounded in real constraints. Designed for real railways.*
