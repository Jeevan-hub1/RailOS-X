# Implementation Plan: RailOS Pilot System

## Overview

This plan covers full implementation of the RailOS Pilot System across 30 task groups, organized in dependency order from infrastructure setup through core subsystems, AI/ML components, security, governance, and operator tooling. Each task group maps to one or more requirements from the 45-requirement specification.

Estimated implementation phases:
- Phase 1 (Tasks 1–5): Infrastructure and data pipeline foundations
- Phase 2 (Tasks 6–13): Core AI subsystems and Digital Twin
- Phase 3 (Tasks 14–22): Authorization, security, governance, and operator UI
- Phase 4 (Tasks 23–30): Testing, validation, and lifecycle management

## Tasks

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1", "16", "17", "19", "20"]
    },
    {
      "wave": 2,
      "tasks": ["2", "15"]
    },
    {
      "wave": 3,
      "tasks": ["3"]
    },
    {
      "wave": 4,
      "tasks": ["4"]
    },
    {
      "wave": 5,
      "tasks": ["5"]
    },
    {
      "wave": 6,
      "tasks": ["6", "7", "8", "10", "11", "12", "13", "25"]
    },
    {
      "wave": 7,
      "tasks": ["9", "18", "21", "28"]
    },
    {
      "wave": 8,
      "tasks": ["14", "26", "27"]
    },
    {
      "wave": 9,
      "tasks": ["22", "23", "24", "29", "30"]
    }
  ]
}
```

1 (Infra) → 2 (Time Sync) → 3 (Adapters) → 4 (Pipeline) → 5 (Edge SW)
4 → 6 (Defect Detector)
4 → 7 (Predictive Maintenance)
4 → 8 (Delay Predictor)
5 → 9 (Federated Learning)
4 → 10 (MARL Scheduler)
4 → 11 (Kavach Advisory)
4 → 12 (Cybersecurity Dashboard)
4 → 13 (Digital Twin)
6,7,8,10,11 → 14 (Authorization Gate)
1 → 15 (RBAC + MFA)
1 → 16 (Supply Chain Security)
1 → 17 (Container Security)
6,7,8,9,10 → 18 (Model Governance CI/CD)
1 → 19 (Observability)
1 → 20 (Disaster Recovery)
18 → 21 (Safety & Compliance)
13,14 → 22 (Operator UI)
6,7,8,9,10,14 → 23 (Property-Based Tests)
13,10 → 24 (Simulation Validation)
4 → 25 (Geographic Isolation)

## Notes

- All tasks involving ML model deployment must pass the benchmark gate (Task 18.2) before production approval.
- Tasks 6–11 (AI subsystems) can be developed and tested in simulation using synthetic sensor data before real IR data is available.
- The Kavach Advisory Layer (Task 11) requires a read-only data tap agreement with the Kavach 4.0 operator before deployment.
- Red-team exercises (Task 27) must run in simulation mode only and must never inject adversarial patterns into the live operational data stream.
- All PostgreSQL tables in the audit, hazard register, and security audit domains are append-only; no UPDATE or DELETE operations are permitted on these tables once created.
- Tasks 18.3 (Fairlearn fairness evaluation) and 18.5 (ART adversarial validation) must run as blocking gates in CI/CD before any model deployment is approved.
18 → 26 (Dataset Governance)
12 → 27 (Red-Team Testing)
5 → 28 (Hardware Telemetry)
14 → 29 (Alert Fatigue Management)
1 → 30 (Data Retention)
```

## Notes
  - [x] 1.1 Deploy Apache Kafka cluster (3 brokers, replication factor 3, min.insync.replicas=2) on Kubernetes
  - [x] 1.2 Deploy InfluxDB 3.0 primary instance with hot standby replica and WAL streaming replication
  - [x] 1.3 Deploy PostgreSQL with Patroni HA (primary + 2 replicas) for audit logs, hazard register, and asset registry
  - [x] 1.4 Deploy Apache Flink cluster (job manager + task managers) on Kubernetes
  - [x] 1.5 Deploy Delta Lake storage layer (Apache Parquet on S3-compatible object store) for historical data
  - [x] 1.6 Deploy PostGIS (PostgreSQL + spatial extensions) for Digital Twin geospatial layer
  - [x] 1.7 Deploy Keycloak identity provider with TOTP MFA support and 4 RBAC role definitions
  - [x] 1.8 Deploy Kong API Gateway with JWT validation, rate-limiting (1000 req/min), and versioned routing plugins
  - [x] 1.9 Deploy HashiCorp Vault with audit device enabled for immutable configuration change logging
  - [x] 1.10 Deploy MinIO with Object Lock (WORM, COMPLIANCE mode) for forensic evidence storage
  - [x] 1.11 Deploy MLflow tracking server and artifact store (S3-backed, geo-replicated)
  - [x] 1.12 Configure Kubernetes cluster with Pod Security Admission (restricted profile) and network policies

- [x] 2. Time Synchronization Infrastructure
  - [x] 2.1 Configure GPS-disciplined PTP grandmaster clock at zone compute node
  - [x] 2.2 Deploy PTP boundary clocks on each station Edge_Node (IEEE 1588)
  - [x] 2.3 Implement `CLOCK_DRIFT_ALERT` emitter: monitor drift >±100ms, publish to monitoring.alerts Kafka topic
  - [x] 2.4 Implement `CLOCK_UNRELIABLE` flag injection into sensor event canonical schema when sync is lost
  - [x] 2.5 Write integration test: simulate clock source failure, verify all subsequent events carry `CLOCK_UNRELIABLE` flag

- [x] 3. Legacy System Adapters
  - [x] 3.1 Implement NTES REST adapter service: polls NTES HTTP API every 30s, transforms to canonical train.telemetry.position events
  - [x] 3.2 Implement OMRS stream adapter service: subscribes to OMRS proprietary stream, transforms to train.telemetry.omrs events
  - [x] 3.3 Implement WILD stream adapter service: subscribes to WILD serial/TCP feed, transforms to train.telemetry.wild events
  - [x] 3.4 Implement dead-letter routing: on 3 consecutive parse failures, emit `LEGACY_ADAPTER_FAILURE` alert and route raw payload to dead-letter.adapter-failures topic
  - [x] 3.5 Expose adapter software version as Prometheus label `adapter_version` on each adapter's metrics endpoint
  - [x] 3.6 Package each adapter as an independently deployable container (no shared process with Data_Pipeline core)
  - [x] 3.7 Write unit tests for each adapter using recorded real-format payload fixtures (NTES, OMRS, WILD)

- [x] 4. Data Pipeline (Kafka + Flink + Storage)
  - [x] 4.1 Create all Kafka topics per §4.1 of design (track.sensor.*, train.telemetry.*, vision.defect.*, signaling.state, monitoring.alerts.*, dead-letter.*, audit.*)
  - [x] 4.2 Implement canonical sensor event JSON schema (§4.3) with schema registry (Confluent Schema Registry or Apicurio)
  - [x] 4.3 Implement schema validation Flink operator: valid events → destination topic; invalid → dead-letter.schema-failures + `SCHEMA_VALIDATION_FAILURE` alert
  - [x] 4.4 Implement InfluxDB writer with 3-retry exponential back-off; emit `STORAGE_WRITE_FAILURE` on exhaustion without silently discarding events
  - [x] 4.5 Implement 90-day retention policy on InfluxDB raw sensor events; archive to Delta Lake on expiry
  - [x] 4.6 Implement Flink stream processing jobs: sensor feature extraction, stream joins (sensor + train position + weather), anomaly rule evaluation
  - [x] 4.7 Implement feed heartbeat watchdog: emit `FEED_UNAVAILABLE` when no heartbeat for ≥10s, maintain 500ms normalization SLA on remaining feeds
  - [x] 4.8 Implement throughput test harness: verify sustained 10,000 events/s ingestion across all active sensor feeds
  - [x] 4.9 Implement Delta Lake compaction and Parquet partitioning by zone, date, and sensor type for efficient ML training queries

- [x] 5. Edge Node Software Stack
  - [x] 5.1 Implement heartbeat watchdog FSM (Connected → Autonomous → Reconnecting) with 3-failure/30s detection threshold
  - [x] 5.2 Implement local NVMe event buffer: circular write with overflow log, minimum 24h capacity management
  - [x] 5.3 Implement reconnection upload protocol: timestamp-ordered upload with per-record ACK, 3-retry/60s per record, continue-on-failure
  - [x] 5.4 Implement non-volatile model weight store: persist active model weights and TensorRT inference runtime to NVMe; verify cold-restart resumes inference without central connectivity
  - [x] 5.5 Implement `STORAGE_THRESHOLD` alerter: at 90% capacity, attempt SMS gateway → local console → audit log + 5-min retry loop
  - [x] 5.6 Package edge software stack as container images (containerd runtime, Ubuntu 22.04 LTS base)

- [x] 6. Track Defect Detector
  - [x] 6.1 Collect and label corridor track defect image dataset: minimum 500 labeled images per Defect_Category (crack, flaking, fastener_loose, spalling), 80/20 train/held-out split
  - [x] 6.2 Fine-tune YOLOv8n on IR corridor defect dataset via transfer learning from COCO pretrained weights
  - [x] 6.3 Export model to TensorRT INT8 quantized engine targeting Jetson Orin NX; verify 100ms inference latency budget
  - [x] 6.4 Implement Grad-CAM heatmap generation (same latency budget as primary inference); store artifact with alert ID reference
  - [x] 6.5 Implement depth estimation branch: when stereo/structured-light feed available, output depth in mm (±5mm accuracy)
  - [x] 6.6 Implement `DEFECT_ALERT` event producer: emit per §6.1 schema to vision.defect.alerts topic regardless of confidence score
  - [x] 6.7 Implement confidence threshold gate: confidence < 0.70 → set `REQUIRES_HUMAN_REVIEW` flag; suppress maintenance dispatch pending OC review
  - [x] 6.8 Implement 4-hour review escalation timer: unreviewed `REQUIRES_HUMAN_REVIEW` alerts escalated to secondary OC after 4h
  - [x] 6.9 Implement SHAP/Grad-CAM feature attribution: top-3 contributing features in plain-language IR domain terminology
  - [x] 6.10 Run benchmark: verify ≥90% precision and ≥90% recall per Defect_Category on held-out 20% test split

- [x] 7. Predictive Maintenance Engine
  - [x] 7.1 Implement 30-minute rolling window feature extractor: 8 features (vibration_rms, kurtosis, peak, temperature, wheel_load_left, wheel_load_right, acoustic_rms, speed) at 1Hz from OMRS/WILD Kafka topics
  - [x] 7.2 Train 2-layer LSTM(128) model with dropout=0.0 at inference (deterministic); wrap with MAPIE ConformalRegressor for calibrated 90% confidence intervals
  - [x] 7.3 Implement linear interpolation for gaps ≤40%: track interpolation percentage, set `DATA_QUALITY` flag in output
  - [x] 7.4 Implement `INSUFFICIENT_DATA` path: if interpolation >40%, withhold score, emit advisory to Data_Pipeline and Digital_Twin with no score field
  - [x] 7.5 Implement CI width enforcement: verify width(p) ≥ width(0%) × (1 + p/20) for p ∈ (0%, 40%]; assert finite non-zero CI for all valid windows
  - [x] 7.6 Implement `MAINTENANCE_ADVISORY` event producer: emit per §6.2 schema when failure_probability > 0.80
  - [x] 7.7 Implement SHAP value computation for top-3 feature attribution with plain-language IR terminology mapping
  - [x] 7.8 Run benchmark: verify deterministic inference (identical output for identical input), calibration error, and CI coverage

- [x] 8. GNN Delay Predictor
  - [x] 8.1 Build Corridor graph dataset: extract station, train, and segment nodes from NTES + IR GIS data; construct heterogeneous edges per §6.3 design
  - [x] 8.2 Implement HetGNN-SAGE model: 2 message-passing layers (128 hidden units), heterogeneous linear transforms per edge type, per-Train output head
  - [x] 8.3 Wrap model with MAPIE conformal predictor to produce 90% prediction interval (lower + upper bounds in minutes)
  - [x] 8.4 Implement NTES snapshot consumer: update graph every 5 minutes from Kafka train.telemetry.position topic; 2s inference latency budget
  - [x] 8.5 Implement `STALE_INPUT` flag: detect NTES feed lag >60s, flag all outputs and propagate flag in REST response body
  - [x] 8.6 Implement REST endpoint `POST /api/v1/delay-predictor/forecast`: return per-train delay forecasts with PI; HTTP 400 with field-level error on malformed input
  - [x] 8.7 Run graceful degradation benchmark: measure MAE on 12-month vs 3-month training data; verify MAE increase ≤15%

- [x] 9. Federated Learning Layer
  - [x] 9.1 Set up Flower (flwr) server on zone compute node with FedAvg strategy configuration
  - [x] 9.2 Implement 5 simulated Edge_Node FL clients with partitioned local datasets (non-IID splits by geographic zone/climate type)
  - [x] 9.3 Integrate Opacus differential privacy: Gaussian noise with configurable σ ∈ [0.0, 10.0] applied to client gradients before upload
  - [x] 9.4 Implement round protocol: 120s client timeout; proceed with ≥3 respondents; abort and emit `ROUND_ABORTED` if <3 respond
  - [x] 9.5 Implement global model quality check: after aggregation, verify global_loss ≤ worst local validation loss across participating nodes
  - [x] 9.6 Implement new-node join protocol: initialize new node with current global weights (gRPC with checksum verification) before first round participation; log `INITIALIZATION_FAILURE` and exclude node from next round if transfer fails/times out in 120s
  - [x] 9.7 Implement gradient transmission protocol: verify only weight deltas (no raw sensor data) leave Edge_Node
  - [x] 9.8 Write FL round integration test: simulate client failures mid-round; verify 3-client minimum enforcement and `ROUND_ABORTED` emission

- [x] 10. MARL Train Scheduler
  - [x] 10.1 Configure Flatland-RL environment to represent Corridor topology: map IR stations and track segments to Flatland grid topology
  - [x] 10.2 Train PPO agent (Stable Baselines3, MLP actor/critic 256×256) on Flatland Corridor environment; reward: minimize total passenger delay with Conflict penalty
  - [x] 10.3 Implement conflict-free constraint layer: post-process every proposed action set, check segment occupation time windows for overlap, reject any action that creates a Conflict before output
  - [x] 10.4 Implement 30s hard timeout: if no conflict-free proposal found within 30s, emit `NO_FEASIBLE_PROPOSAL` to Operations_Controller within 35s
  - [x] 10.5 Implement rejection loop: alternative proposals must differ in assignment pattern from rejected proposal; after 3 consecutive rejections emit `SCHEDULING_ESCALATION`
  - [x] 10.6 Implement rescheduling proposal JSON producer: emit per §6.5 schema to scheduling.proposals Kafka topic
  - [x] 10.7 Write PBT: use Hypothesis to verify conflict-free invariant across ≥1,000 randomly generated disruption scenarios

- [x] 11. Kavach++ Advisory Layer
  - [x] 11.1 Implement read-only data tap from Kavach 4.0 telemetry (via data diode read interface in Zone 2); verify zero write path to Zone 3/4
  - [x] 11.2 Implement 1D-CNN adhesion coefficient classifier: input bogie vibration window, output μ estimate (0.1–0.35)
  - [x] 11.3 Implement DEM-backed track gradient lookup: GPS coordinate → elevation model → gradient angle θ
  - [x] 11.4 Implement physics-based braking curve calculator: stopping_distance = v² / (2μg·cos(θ) + 2g·sin(θ))
  - [x] 11.5 Implement safety invariant check: assert advisory_stopping_distance(v) ≥ kavach_certified_stopping_distance(v) for all v; if violated, suppress advisory
  - [x] 11.6 Implement `KAVACH_ADVISORY_UNAVAILABLE` path: if required sensor data absent, withhold advisory and set unavailable status
  - [x] 11.7 Implement advisory event producer: label all outputs "ADVISORY — NOT CERTIFIED" in payload metadata and UI panel
  - [x] 11.8 Write PBT: use Hypothesis to verify stopping distance conservatism invariant across sampled speed/condition combinations

- [x] 12. Cybersecurity LSTM Autoencoder and Dashboard
  - [x] 12.1 Train LSTM autoencoder (128→64→128 hidden units) on normal SCADA traffic baseline (anomaly-free)
  - [x] 12.2 Implement rolling window consumer: 60s window, 10s stride (50s overlap) from SCADA traffic Kafka topic
  - [x] 12.3 Implement anomaly scorer: compute reconstruction MSE; if > configurable threshold emit `SECURITY_ANOMALY` to security.anomalies topic with IEC 62443 zone, timestamp, error value
  - [x] 12.4 Implement forensic capture: on any anomaly, write raw 60s traffic window + reconstruction error vector + metadata to MinIO WORM bucket as `{alertId}.tar.gz`
  - [x] 12.5 Implement forensic evidence package API: `GET /api/v1/forensics/{alertId}/package` → downloadable archive within 5 minutes; accessible to Security_Officer role only
  - [x] 12.6 Build Grafana Cybersecurity Dashboard: IEC 62443 zone status panels (green/amber/red), anomaly timeline, unacknowledged alert queue, 15-min escalation timer display
  - [x] 12.7 Implement acknowledgement workflow: Security_Officer must acknowledge before alert clears; unacknowledged alerts escalate after 15 min to next on-call officer
  - [x] 12.8 Implement append-only audit log for `SECURITY_ANOMALY` events and acknowledgements (PostgreSQL trigger: no UPDATE/DELETE on security_audit table)
  - [x] 12.9 Implement red-team simulation mode: dedicated Kafka topic for synthetic adversarial SCADA injection; simulation mode runs without affecting live operational stream

- [x] 13. Digital Twin
  - [x] 13.1 Build PostGIS asset registry: import IR GIS track geometry (LineString, EPSG:4326) and station/bridge/tunnel assets; add spatial indexes
  - [x] 13.2 Build InfluxDB real-time state store: Kafka consumer group subscribing to all advisory and telemetry topics; update state on each event
  - [x] 13.3 Implement state conflict detector: reject topology-violating updates (position outside track geometry, two trains on same segment); log inconsistency with source event ID and timestamp
  - [x] 13.4 Implement OpenTrack simulation integration: import Corridor timetable, expose what-if scenario API for MARL proposal visualization
  - [x] 13.5 Build Three.js + Deck.gl frontend: render GIS corridor map with train position markers (≤5s refresh via WebSocket), defect markers, maintenance asset highlights, delay overlay
  - [x] 13.6 Implement visual encoding convention per §7.2: solid=confirmed, dashed=predicted, hatched=simulated, faded=stale; PI band overlay for delay forecasts and CI bars for failure probability
  - [x] 13.7 Implement persistent legend panel: always-visible, defines all encoding conventions (confirmed/predicted/simulated/stale/advisory)
  - [x] 13.8 Implement staleness indicator: if train position not updated >10s, display staleness icon on marker
  - [x] 13.9 Implement predicted→confirmed transition: update visual encoding within 3s of confirming sensor event receipt
  - [x] 13.10 Implement geographic isolation zone overlay: render zone boundaries, show zone-isolated degraded mode indicator when active
  - [x] 13.11 Performance test: verify ≥30 fps rendering of 200 concurrent train positions on 1920×1080 workstation

- [x] 14. Human-in-the-Loop Authorization Gate
  - [x] 14.1 Implement risk score computation: risk_score = probability × severity_weight (CRITICAL=4, HIGH=3, MEDIUM=2, LOW=1); assert score ∈ [0.0, 4.0]
  - [x] 14.2 Implement risk tier classifier: Tier 1 ≥3.2 (dual-auth), Tier 2 2.0–3.19 (single-auth), Tier 3 <2.0 (standard)
  - [x] 14.3 Implement advisory queue: hold all advisories pending OC action; severity-descending order display; escalate to secondary OC after 10 min
  - [x] 14.4 Implement Tier 1 dual-authorization: require two distinct OC identity tokens before forwarding; record both in audit log
  - [x] 14.5 Implement authorization gate availability monitor: publish gate status (operational/degraded/unavailable) as Prometheus metric and Digital_Twin status indicator
  - [x] 14.6 Implement gate-unavailable hold: when gate unavailable, hold all advisories in queue, forward nothing until gate restored and OC reviews queue
  - [x] 14.7 Implement advisory authorization audit log: append-only record per §12 schema (auditId, advisoryId, action, identities, timestamp, riskTier, riskScore, modelVersion, configVersion)
  - [x] 14.8 Write PBT: use Hypothesis to verify no advisory reaches downstream without authorization record

- [x] 15. Role-Based Access Control and MFA
  - [x] 15.1 Configure Keycloak: create 4 roles (Operations_Controller, Security_Officer, Engineering_Team, Governance_Officer) with permission scopes per §9.1 design
  - [x] 15.2 Enable TOTP MFA on all privileged role accounts in Keycloak; configure MFA enforcement policy
  - [x] 15.3 Configure Kong Gateway JWT plugin: validate RS256 JWT from Keycloak JWKS endpoint; reject unauthenticated requests with HTTP 401
  - [x] 15.4 Implement role-enforcement middleware on all RailOS service endpoints: deny out-of-scope actions with HTTP 403 + audit log entry (user identity, attempted action, timestamp)
  - [x] 15.5 Write integration test: verify each role cannot perform actions outside its defined permission scope

- [x] 16. Supply Chain Security
  - [x] 16.1 Integrate cosign (Sigstore) into CI/CD pipeline: sign all container images at build time; verify signatures before Kubernetes deployment
  - [x] 16.2 Integrate Syft: generate SBOM in CycloneDX JSON format for each deployment release; store in model governance artifact store
  - [x] 16.3 Integrate Grype: scan SBOM against NVD on every build; block deployment on HIGH/CRITICAL CVE detection
  - [x] 16.4 Implement NVD feed poller: check every 24h for new CVEs affecting components in the active SBOM; emit `CVE_ALERT` to Engineering_Team within 24h of NVD publication
  - [x] 16.5 Retain SBOM per deployment release for minimum 365 days in artifact store

- [x] 17. Container Security
  - [x] 17.1 Apply Kubernetes Pod Security Admission (restricted profile) to all RailOS namespaces: runAsNonRoot, allowPrivilegeEscalation=false, capabilities drop ALL, readOnlyRootFilesystem where feasible
  - [x] 17.2 Document and record in hazard register any subsystem requiring write access to root filesystem (residual risk acceptance per Req 39 C1)
  - [x] 17.3 Deploy Falco with RailOS-specific rules: detect and alert on privilege escalation attempts in any RailOS container
  - [x] 17.4 Implement `PRIVILEGE_ESCALATION_ALERT` handler: emit to Security_Officer, log container name + timestamp + attempted capability, terminate container within 30s

- [x] 18. Model Governance and CI/CD Pipeline
  - [x] 18.1 Configure MLflow tracking: all model training runs log parameters, metrics, and artifacts with MAJOR.MINOR.PATCH version tags; link run IDs to requirement IDs in traceability matrix
  - [ ] 18.2 Implement benchmark gate (pytest): runs before any model deployment approval; covers inference latency, precision/recall, calibration, MAE, conflict-free rate per §16 Technology Stack
  - [ ] 18.3 Implement Fairlearn fairness evaluation: partition held-out dataset by 3 strata (weather, time-of-day, infrastructure region); block deployment on >10% stratum degradation + emit `BIAS_THRESHOLD_EXCEEDED`
  - [ ] 18.4 Implement Evidently AI drift monitor: compute daily PSI rolling window for each deployed model; emit `MODEL_DRIFT_ALERT` + apply `DRIFT_WARNING` to outputs after 3 consecutive days PSI ≥ 0.2
  - [ ] 18.5 Implement ART adversarial validation: FGSM perturbation test on each model before deployment; block if primary metric degrades >15% on adversarial test set
  - [ ] 18.6 Integrate DVC for dataset versioning: track all training/evaluation dataset versions with provenance metadata (source, preprocessing steps, annotation tool version, timestamp range, approving team member)
  - [x] 18.7 Implement model rollback API: `POST /api/v1/models/{modelId}/rollback`; complete within 15 min without Edge_Node restart; abort with `ROLLBACK_TIMEOUT` if exceeded; return `NO_PREVIOUS_VERSION` error if no prior version exists

- [x] 19. Observability Stack
  - [x] 19.1 Deploy Prometheus with scrape configurations for all RailOS services; deploy Grafana with operational dashboards covering all key metrics defined in §8
  - [x] 19.2 Instrument all services with OpenTelemetry SDK; deploy Jaeger collector and UI for distributed trace visualization
  - [x] 19.3 Configure all services to emit structured JSON logs; deploy Elasticsearch + Kibana for log aggregation and search
  - [x] 19.4 Configure Alertmanager: route `SUBSYSTEM_DEGRADED` (>1% error rate over 5-min window) alerts to PagerDuty/SMS gateway
  - [x] 19.5 Implement end-to-end alert latency trace: instrument sensor_ingest → kafka_publish → flink_process → ml_inference → advisory_emit → digital_twin_render → websocket_push trace chain
  - [x] 19.6 Implement latency SLA monitor: log breach when e2e delivery >5s (alert ID, measured latency, pipeline stage); expose p50/p95/p99 as Prometheus metric on 1-min rolling basis
  - [x] 19.7 Configure telemetry retention: 30-day minimum for all Prometheus metrics; configure InfluxDB and Elasticsearch retention policies accordingly

- [x] 20. Disaster Recovery
  - [x] 20.1 Verify Kafka cluster RF=3 and min.insync.replicas=2; test broker failure and automatic leader election
  - [x] 20.2 Configure InfluxDB continuous WAL replication to hot standby; verify replication lag ≤60s
  - [x] 20.3 Configure PostgreSQL Patroni HA: automatic failover; verify RPO ≤60s and RTO ≤2 min on primary failure
  - [x] 20.4 Configure geo-replicated backups: daily automated snapshots of all PostgreSQL databases and MLflow artifacts to geographically separate storage node
  - [x] 20.5 Implement daily automated restore integrity test: restore latest backup to isolated test environment; emit `BACKUP_INTEGRITY_FAILURE` alert if test fails
  - [x] 20.6 Document full-system restore runbook targeting RTO ≤30 min from catastrophic failure
  - [x] 20.7 Test 24h Edge_Node autonomous operation: simulate complete central infrastructure outage and verify local inference, buffering, and alert continuity

- [x] 21. Safety and Compliance
  - [x] 21.1 Implement traceability matrix store (PostgreSQL): schema per §13.1; link requirement IDs to MLflow run IDs, hazard IDs, and verification evidence records
  - [x] 21.2 Implement traceability report API: `GET /api/v1/traceability/{subsystemVersion}` → JSON/PDF report within 5 min; accessible to Engineering_Team and Security_Officer roles
  - [x] 21.3 Implement hazard register (PostgreSQL append-only table per §13.2 schema): `HAZARD_REVIEW_REQUIRED` trigger on repeated anomaly patterns; accessible to Security_Officer and Engineering_Team only
  - [x] 21.4 Implement Vault-backed configuration versioning: all thresholds, suppression windows, drift PSI values, and deployment parameters stored in Vault with immutable audit log (key, prev_value, new_value, identity, UTC timestamp)
  - [x] 21.5 Verify EN 50128 alignment: audit all deployed ML inference paths for deterministic behavior (no stochastic layers at inference, fixed-point quantization, version-controlled model artifacts)

- [ ] 22. Operator UI
  - [ ] 22.1 Build React + Three.js + Deck.gl operations dashboard shell: routing, authentication integration with Keycloak, session management
  - [ ] 22.2 Implement advisory panel: severity-descending queue, max 5 visible + scrollable overflow with count badge, RED/AMBER/YELLOW/BLUE color coding per IR Operations Manual terminology
  - [ ] 22.3 Implement Authorize/Reject controls: minimum 44×44 CSS px, visually distinct from non-interactive elements by color AND shape/border
  - [ ] 22.4 Implement Tier 1 dual-authorization UI: require second OC identity before forwarding; show pending second-auth status clearly
  - [ ] 22.5 Implement deduplication display: show suppression counter on original alert; update existing advisory on duplicate `MAINTENANCE_ADVISORY` for same asset
  - [ ] 22.6 Implement `DRIFT_WARNING` indicator: display visible flag alongside advisory when model drift is active
  - [ ] 22.7 Implement high-contrast mode and reduced-motion mode: toggleable from dashboard settings without session restart
  - [ ] 22.8 Run WCAG 2.1 Level AA audit: verify color contrast ratios, text sizing, keyboard navigability across all operator interface components

- [x] 23. Property-Based Tests
  - [x] 23.1 Implement PBT: MARL conflict-free invariant (Hypothesis, ≥1,000 disruption scenarios) — Property 1
  - [x] 23.2 Implement PBT: Kavach advisory conservatism (Hypothesis, sampled speeds + track conditions) — Property 2
  - [x] 23.3 Implement PBT: FL global model quality bound (Hypothesis, sampled round data with ≥3 clients) — Property 3
  - [x] 23.4 Implement PBT: CI monotonic widening (Hypothesis, sampled interpolation percentages 0–40%) — Property 4
  - [x] 23.5 Implement PBT: risk score bounds [0.0, 4.0] (Hypothesis, all advisory types and probability values) — Property 5
  - [x] 23.6 Implement PBT: authorization gate enforcement (Hypothesis, verify no downstream delivery without auth record) — Property 6
  - [x] 23.7 Implement benchmark test: delay predictor MAE degradation ≤15% at 3-month vs 12-month training data — Property 7

- [ ] 24. Simulation Validation
  - [x] 24.1 Prepare held-out historical IR movement dataset: minimum 30 days of actual train movement records from NTES historical archive
  - [x] 24.2 Validate Digital Twin simulation engine against historical dataset: verify mean absolute position error ≤500m at all trajectory points; record result in model governance audit log
  - [x] 24.3 Prepare 100 historical disruption scenarios reconstructed from NTES historical data (cancelled services, delayed services, blocked segments)
  - [x] 24.4 Evaluate MARL_Scheduler on 100 historical disruption scenarios: verify ≥70% produce conflict-free proposals within 30s; record result in audit log

- [ ] 25. Geographic Failure Isolation
  - [ ] 25.1 Define Corridor geographic isolation zones: map contiguous station/segment sets to named zones; configure dedicated Kafka topic partitions per zone
  - [ ] 25.2 Implement zone-isolated degraded mode: on repeated `SUBSYSTEM_DEGRADED` alerts from one zone, isolate that zone's Flink processing units without affecting other zones
  - [ ] 25.3 Implement Digital Twin zone isolation indicator: display affected zone boundary with degradation reason; do not suppress advisories from unaffected zones
  - [x] 25.4 Write integration test: simulate zone-A subsystem failure; verify zone-B advisory throughput is unaffected

- [ ] 26. Dataset Governance
  - [ ] 26.1 Configure DVC for all training and evaluation datasets: version tag each dataset with source identifiers, preprocessing pipeline hash, annotation tool version, timestamp range, and approving Engineering_Team member
  - [ ] 26.2 Implement dataset-model linkage in traceability matrix: when model approved for deployment, link model version to training and evaluation dataset version IDs
  - [ ] 26.3 Implement dataset provenance report API: on request from Governance_Officer, return provenance record for any dataset version
  - [ ] 26.4 Configure dataset record retention: minimum 365 days for all dataset version records and provenance metadata

- [ ] 27. Red-Team and Adversarial Testing
  - [ ] 27.1 Implement red-team simulation mode for Cybersecurity Dashboard (Req 43 C1): dedicated Kafka topic for adversarial SCADA injection; simulation runs isolated from live stream
  - [ ] 27.2 Build adversarial SCADA pattern library: replay attacks, injection patterns, anomalous polling sequences (minimum 20 distinct pattern types)
  - [ ] 27.3 Run red-team exercise and measure detection rate: verify ≥80% of injected anomaly events trigger `SECURITY_ANOMALY` within 60s window; record result in audit log
  - [ ] 27.4 Run ART FGSM adversarial evaluation on all deployed ML models: verify primary metric degradation ≤15% on adversarial test set; record results in audit log

- [x] 28. Edge Node Hardware Telemetry and Thermal Protection
  - [x] 28.1 Implement hardware telemetry collector on each Edge_Node: sample CPU temp, GPU utilization, memory utilization, storage utilization, power status every 10s
  - [x] 28.2 Expose all hardware metrics as Prometheus-compatible metrics at Edge_Node telemetry endpoint (compatible with §19 observability stack)
  - [x] 28.3 Implement thermal protection logic: on CPU/GPU temp > OEM threshold, throttle inference threads + emit `THERMAL_PROTECTION_ACTIVE` alert
  - [x] 28.4 Implement thermal recovery: restore full inference capacity only after 60 consecutive seconds below OEM threshold; log throttle and restore events

- [x] 29. Alert Fatigue Management
  - [x] 29.1 Implement geographic deduplication: suppress duplicate `DEFECT_ALERT` events for same GPS coordinate (within 50m radius) + same Defect_Category within configurable suppression window (default 10 min); increment suppression counter on original alert
  - [x] 29.2 Implement advisory update-in-place: when `MAINTENANCE_ADVISORY` emitted for asset with existing active advisory, update probability score and timestamp rather than creating new entry
  - [x] 29.3 Implement suppression counter display in Operator UI: show count of suppressed duplicates on each active advisory entry
  - [x] 29.4 Implement Vault-backed suppression window configuration: suppression window is a versioned config parameter per §21.4

- [x] 30. Data Retention Lifecycle
  - [x] 30.1 Implement per-category retention policies with defaults: raw sensor events (90d), inference audit logs (365d), security anomaly records (365d), forensic evidence (365d), telemetry metrics (30d), model artifacts (indefinite until explicit deletion)
  - [x] 30.2 Implement automated archive/purge job: at retention expiry, archive to cold storage or purge per policy; skip records under active forensic hold
  - [x] 30.3 Implement forensic hold API: `POST /api/v1/retention/holds` (Security_Officer or Governance_Officer role); prevents purging of associated records until hold released
  - [x] 30.4 Implement monthly data retention compliance report: total records archived/purged per category, overdue records, current storage consumption per category; accessible to Governance_Officer role
