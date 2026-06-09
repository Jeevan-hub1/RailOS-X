# Requirements Document

## Introduction

The RailOS Pilot System is a corridor-scale cognitive railway operating system built for Indian Railways (IR),
scoped to a single zone or division (e.g., South Central Railway's Kavach-covered ~1,452 km network).
It integrates real-time sensor data pipelines, edge AI for defect detection, predictive maintenance,
graph-based delay forecasting, federated learning, multi-agent train rescheduling simulation, a digital
twin visualization layer, a cybersecurity monitoring dashboard, and a read-only advisory overlay on top
of Kavach 4.0 — all governed by a strict human-in-the-loop principle and EN 50128 / IEC 62443 compliance
requirements.

The pilot does **not** deploy 6G infrastructure, does **not** alter certified Kavach 4.0 safety logic,
and does **not** operate at national scale. All safety-affecting ML outputs are advisory and require human
authorization before action.

---

## Glossary

- **RailOS**: The RailOS Pilot System — the software system described in this document.
- **Data_Pipeline**: The real-time ingestion and normalization subsystem built on Apache Kafka, Apache Flink,
  and InfluxDB 3.0.
- **Edge_Node**: An NVIDIA Jetson Orin NX/AGX computing unit deployed at a station or trackside location,
  responsible for local inference and local storage.
- **Defect_Detector**: The YOLOv8-based computer vision model running on Edge_Nodes that detects rail
  surface defects (cracks, flaking, fastener issues) from camera feeds.
- **Predictive_Maintenance_Engine**: The LSTM/GRU time-series model that forecasts bearing and track
  component failure from sensor streams.
- **Delay_Predictor**: The HetGNN (Heterogeneous Graph Neural Network) model that forecasts train delay
  propagation across the corridor network.
- **Federated_Learning_Layer**: The Flower (flwr) framework component that coordinates FedAvg-based
  model aggregation across simulated zone Edge_Nodes without centralizing raw sensor data.
- **MARL_Scheduler**: The multi-agent reinforcement learning component (PPO-based, Flatland-RL
  environment) that proposes train rescheduling solutions.
- **Digital_Twin**: The Three.js + Deck.gl + OpenTrack visualization layer showing real-time train
  positions, sensor alerts, and defect detections on a GIS corridor map.
- **Cybersecurity_Dashboard**: The Grafana-based IEC 62443-aligned zone security monitoring dashboard
  with LSTM autoencoder anomaly detection on simulated SCADA traffic.
- **Kavach_Advisory_Layer**: The read-only ML-enhanced advisory overlay that presents braking curve
  recommendations derived from Kavach 4.0 data without modifying certified Kavach logic.
- **Operations_Controller**: The human operator authorized to view and act on advisory outputs from
  RailOS subsystems.
- **NTES**: National Train Enquiry System — historical and live train position/delay data source.
- **OMRS/WILD**: Oscillation Monitoring and Recording System / Wheel Impact Load Detector — trackside
  sensor systems providing bearing and wheel health data.
- **Corridor**: The pilot deployment scope — a single IR zone or division network segment.
- **Zone_3/4_System**: Safety-critical and control network segments as defined by IEC 62443 zone
  classification (e.g., ATP/ATC systems, interlocking).
- **SIL-4**: Safety Integrity Level 4 as defined by EN 50128 — the highest safety level, applicable to
  certified Kavach logic.
- **FedAvg**: Federated Averaging algorithm — the aggregation method used by the Federated_Learning_Layer.
- **Defect_Category**: A named class of detectable rail surface defect (crack, flaking, fastener
  loosening, surface spalling).
- **Conflict**: A scheduling state in which two or more trains are assigned to the same track segment
  at overlapping times.
- **Prometheus**: Open-source monitoring and alerting toolkit used for system telemetry collection.
- **Grad-CAM**: Gradient-weighted Class Activation Mapping — a technique for producing visual
  explanations of CNN decisions by highlighting discriminative image regions.
- **RBAC**: Role-Based Access Control — a method of restricting system access based on the roles of
  individual users.
- **MFA**: Multi-Factor Authentication — an authentication method requiring two or more verification
  factors.
- **UTC**: Coordinated Universal Time — the primary time standard used for time synchronization
  across RailOS subsystems.
- **PTP**: Precision Time Protocol (IEEE 1588) — a protocol used to synchronize clocks across a
  computer network to sub-microsecond accuracy.
- **Security_Officer**: An authorized user with permission to acknowledge and manage cybersecurity
  alerts and access the Cybersecurity_Dashboard.
- **Engineering_Team**: Personnel responsible for model deployment, rollback, benchmark review, and
  system maintenance.
- **Governance_Officer**: An authorized data governance user with permission to request data lineage
  reports and configure retention policies.

---

## Requirements

---

### Requirement 1: Real-Time Sensor Data Ingestion

**User Story:** As an Operations_Controller, I want sensor data from trackside instruments and rolling
stock to be continuously ingested and normalized, so that all downstream ML models operate on a
consistent, low-latency data stream.

#### Acceptance Criteria

1. THE Data_Pipeline SHALL ingest data from OMRS, WILD, GPS, vibration, and temperature sensor feeds
   across the Corridor.
2. WHEN a sensor event arrives at the Data_Pipeline, THE Data_Pipeline SHALL normalize the event into
   a canonical schema and publish it to the corresponding Kafka topic within 500 ms of receipt.
3. WHEN a sensor feed produces no heartbeat for 10 or more consecutive seconds, THE Data_Pipeline
   SHALL emit a `FEED_UNAVAILABLE` alert to the monitoring topic and continue maintaining the 500 ms
   normalization SLA on all remaining active feeds without interruption.
4. THE Data_Pipeline SHALL retain raw sensor events in InfluxDB 3.0 for a minimum of 90 days for
   audit and retraining purposes.
5. WHEN data from heterogeneous sensor sources arrives in different binary formats, THE Data_Pipeline
   SHALL apply format-specific adapters to transform each source format into the canonical schema as a
   prerequisite step before normalization and publishing.
6. THE Data_Pipeline SHALL support a sustained ingestion throughput of at least 10,000 events per
   second across all active sensor feeds combined.
7. WHEN a sensor event fails canonical schema validation after adapter transformation, THE Data_Pipeline
   SHALL route the malformed event to a dead-letter Kafka topic, emit a `SCHEMA_VALIDATION_FAILURE`
   alert containing the source feed identifier and raw event payload, and SHALL NOT publish the
   malformed event to the destination topic.
8. WHEN an InfluxDB write operation fails for a validated sensor event, THE Data_Pipeline SHALL retry
   the write up to 3 times with exponential back-off before emitting a `STORAGE_WRITE_FAILURE` alert;
   THE Data_Pipeline SHALL NOT silently discard the event if all retries are exhausted.

---

### Requirement 2: Edge Node Autonomous Operation

**User Story:** As an Operations_Controller, I want Edge_Nodes to continue local inference and alerting
even when central connectivity is lost, so that station-level safety advisories are not disrupted
during network outages.

#### Acceptance Criteria

1. WHEN an Edge_Node detects 3 consecutive failed heartbeats to the central Data_Pipeline within any
   30-second window, THE Edge_Node SHALL transition to autonomous mode and continue executing local
   inference using the most recently synchronized model versions.
2. WHILE an Edge_Node is in autonomous mode, THE Edge_Node SHALL buffer sensor events and inference
   results in local storage up to the available capacity for a minimum of 24 hours; WHEN the local
   buffer is full before 24 hours have elapsed, THE Edge_Node SHALL overwrite the oldest buffered
   entries and record each overwrite in a local overflow log.
3. WHEN connectivity to the central Data_Pipeline is restored, THE Edge_Node SHALL upload all buffered
   events and results ordered by sensor-event timestamp, acknowledging each record with the central
   pipeline before removing it from the local buffer; WHEN a record upload fails after 3 retries
   within 60 seconds, THE Edge_Node SHALL log the failure and proceed to the next buffered record.
4. THE Edge_Node SHALL store the current active model weights and inference runtime in non-volatile
   local storage so that a cold restart does not require central connectivity to resume operation.
5. WHEN local storage on the Edge_Node reaches 90% capacity during autonomous mode, THE Edge_Node
   SHALL first attempt to send a `STORAGE_THRESHOLD` alert via SMS gateway; IF the SMS gateway is
   unreachable, THE Edge_Node SHALL display the alert on the local operator console; IF both channels
   are unavailable, THE Edge_Node SHALL record the threshold event in the local audit log and retry
   both channels at 5-minute intervals.

---

### Requirement 3: Track Defect Detection

**User Story:** As an Operations_Controller, I want automated detection of rail surface defects from
trackside camera feeds, so that maintenance teams can be dispatched to known defect locations before
failures occur.

#### Acceptance Criteria

1. WHEN a camera frame is received by the Defect_Detector, THE Defect_Detector SHALL classify the
   frame as defect-free or assign it to one or more Defect_Categories within 100 ms of frame receipt
   on the Edge_Node.
2. THE Defect_Detector SHALL achieve a precision of at least 90% and a recall of at least 90% on each
   Defect_Category when evaluated on the held-out 20% test split of the corridor defect dataset.
3. WHEN a defect is detected, THE Defect_Detector SHALL emit a `DEFECT_ALERT` event containing the
   Defect_Category, confidence score, GPS coordinate, timestamp, and Edge_Node identifier to the
   Data_Pipeline regardless of the confidence score value.
4. WHEN a `DEFECT_ALERT` is emitted with a confidence score below 0.70, THE Defect_Detector SHALL
   include a `REQUIRES_HUMAN_REVIEW` flag in the alert payload, and THE RailOS SHALL withhold
   automatic maintenance dispatch until an Operations_Controller reviews and authorizes the alert.
5. WHEN a `REQUIRES_HUMAN_REVIEW` alert has not been reviewed by an Operations_Controller within
   4 hours of emission, THE RailOS SHALL escalate the alert to a secondary Operations_Controller
   and log the escalation event with a timestamp.
6. THE Defect_Detector SHALL operate using TensorFlow Lite or TensorRT-optimized model weights
   to meet the 100 ms inference latency requirement on Jetson Orin NX hardware.
7. WHERE the camera feed provides stereo or structured-light depth data, THE Defect_Detector SHALL
   include estimated defect depth in millimetres, accurate to within ±5 mm, in the `DEFECT_ALERT`
   payload.

---

### Requirement 4: Predictive Maintenance Engine

**User Story:** As an Operations_Controller, I want time-series forecasts of bearing and track
component failure risk, so that maintenance can be scheduled proactively before unplanned failures
cause service disruptions.

#### Acceptance Criteria

1. WHEN the Predictive_Maintenance_Engine receives a continuous 30-minute rolling window of OMRS and
   WILD sensor readings for a monitored asset, THE Predictive_Maintenance_Engine SHALL produce a
   failure-probability score in the range [0.0, 1.0] for that asset covering the next 72-hour
   horizon within 10 seconds of the window boundary.
2. WHEN the failure-probability score for an asset exceeds 0.80, THE Predictive_Maintenance_Engine
   SHALL emit a `MAINTENANCE_ADVISORY` event to the Data_Pipeline and to the Digital_Twin containing
   the asset identifier, failure-probability score, confidence interval lower bound, confidence
   interval upper bound, and UTC timestamp.
3. THE Predictive_Maintenance_Engine SHALL produce failure-probability scores that are reproducible:
   given identical input windows, THE Predictive_Maintenance_Engine SHALL return identical scores
   (deterministic inference).
4. WHEN sensor readings in the input window contain gaps exceeding 5 minutes, THE
   Predictive_Maintenance_Engine SHALL interpolate missing values using linear interpolation and
   include a `DATA_QUALITY` flag in the output indicating the percentage of interpolated samples.
5. IF the percentage of interpolated samples in the input window exceeds 40%, THEN THE
   Predictive_Maintenance_Engine SHALL withhold the failure-probability score, emit an
   `INSUFFICIENT_DATA` advisory to both the Data_Pipeline and the Digital_Twin, and SHALL NOT
   include a score field in the output payload.
6. IF the `DATA_QUALITY` interpolation percentage p is in the range (0%, 40%], THEN THE output
   confidence interval width SHALL be at least (1 + p/20) times the baseline confidence interval
   width measured at p = 0% for the same input asset and window length, ensuring the interval
   widens monotonically with data quality degradation.
7. THE Predictive_Maintenance_Engine output confidence interval SHALL remain finite and non-zero
   for all valid input windows where the interpolation percentage is ≤ 40%, preventing degenerate
   output states.

---

### Requirement 5: GNN-Based Train Delay Prediction

**User Story:** As an Operations_Controller, I want forecasts of delay propagation across the
Corridor, so that knock-on delays can be anticipated and resources repositioned before disruption
spreads.

#### Acceptance Criteria

1. WHEN the Delay_Predictor receives a snapshot of current train positions and delay states from
   the NTES feed, THE Delay_Predictor SHALL produce per-train delay forecasts for a 60-minute
   prediction horizon within 2 seconds of snapshot receipt; each forecast SHALL include a point
   estimate in minutes and a 90% prediction interval expressed as lower and upper bound values
   in minutes.
2. THE Delay_Predictor SHALL model the Corridor as a heterogeneous graph where nodes represent
   stations, trains, and track segments, and edges represent physical connectivity and train
   movement relationships.
3. WHEN the NTES feed is delayed by more than 60 seconds, THE Delay_Predictor SHALL use the most
   recent available snapshot and include a `STALE_INPUT` flag in all outputs until a fresh snapshot
   is received; the `STALE_INPUT` flag SHALL also be propagated in the REST response body.
4. THE Delay_Predictor SHALL degrade gracefully as historical NTES data coverage decreases: mean
   absolute error on the held-out test set — defined as the most recent 20% of available data
   ordered by timestamp — SHALL increase by no more than 15% relative to the MAE baseline
   established on 12 months of training data when training data is reduced to 3 months.
5. THE Delay_Predictor SHALL expose a REST endpoint that accepts a corridor snapshot payload and
   returns the delay forecast in JSON format; WHEN the incoming payload is malformed or missing
   required fields, THE endpoint SHALL return HTTP 400 with a structured error body identifying
   the missing or invalid fields.

---

### Requirement 6: Federated Learning Layer

**User Story:** As a system architect, I want model improvements to be shared across simulated zone
Edge_Nodes without transmitting raw sensor data to a central server, so that model quality improves
collaboratively while preserving data locality.

#### Acceptance Criteria

1. THE Federated_Learning_Layer SHALL coordinate FedAvg aggregation rounds across at least 5
   simulated zone Edge_Node clients using the Flower (flwr) framework.
2. WHEN a global aggregation round completes, THE Federated_Learning_Layer SHALL produce a global
   model whose validation loss on each participating Edge_Node's local held-out set — withheld
   from training prior to the round — is no greater than the highest validation loss recorded
   among all participating nodes on their respective local held-out sets in that same round.
3. THE Federated_Learning_Layer SHALL transmit only model weight gradients or weight deltas between
   Edge_Nodes and the aggregation server; raw sensor data SHALL NOT be transmitted outside the
   Edge_Node.
4. WHEN an Edge_Node fails to respond within the round timeout of 120 seconds, THE
   Federated_Learning_Layer SHALL proceed with the aggregation round using the responding clients
   and log the absent Edge_Node identifier; IF fewer than 3 Edge_Nodes respond within the timeout,
   THE Federated_Learning_Layer SHALL abort the round, log all absent Edge_Node identifiers, and
   schedule a retry after 300 seconds.
5. IF fewer than 3 Edge_Nodes are available to participate in an aggregation round after the
   timeout window, THEN THE Federated_Learning_Layer SHALL abort the round without producing a
   new global model, emit a `ROUND_ABORTED` event containing the round identifier and the list
   of absent Edge_Node identifiers, and retain the previous global model as the current model.
6. THE Federated_Learning_Layer SHALL support differential privacy by applying Gaussian noise with
   a configurable noise multiplier σ in the range [0.0, 10.0] inclusive to client gradients before
   aggregation.
7. WHEN a new Edge_Node joins the federation, THE Federated_Learning_Layer SHALL initialize the
   new node with the current global model weights before that node participates in the next
   aggregation round.
8. IF the weight initialization transfer to a new Edge_Node fails or does not complete within
   120 seconds, THEN THE Federated_Learning_Layer SHALL exclude the new node from the next
   aggregation round, log the initialization failure with the Edge_Node identifier and error
   reason, and retry initialization before the subsequent round.

---

### Requirement 7: MARL Train Scheduling Simulation

**User Story:** As an Operations_Controller, I want a rescheduling proposal generated automatically
when disruptions are detected, so that recovery options can be evaluated quickly without manual
timetabling.

#### Acceptance Criteria

1. WHEN the MARL_Scheduler receives a disruption event (cancelled service, delayed service, or
   blocked track segment) from the Data_Pipeline, THE MARL_Scheduler SHALL produce a rescheduling
   proposal within 30 seconds.
2. THE MARL_Scheduler SHALL guarantee that every rescheduling proposal is free of Conflicts: no
   two trains in the proposal SHALL be assigned to the same track segment at overlapping times.
3. THE MARL_Scheduler SHALL present rescheduling proposals exclusively as advisories to the
   Operations_Controller; THE MARL_Scheduler SHALL NOT autonomously dispatch commands to
   Zone_3/4_Systems.
4. WHEN the Operations_Controller rejects a rescheduling proposal, THE MARL_Scheduler SHALL
   generate an alternative proposal that does not repeat the rejected assignment pattern within
   60 seconds; IF 3 consecutive proposals are rejected, THE MARL_Scheduler SHALL emit a
   `SCHEDULING_ESCALATION` event to the Operations_Controller indicating that human manual
   timetabling is required.
5. THE MARL_Scheduler SHALL use the Flatland-RL environment configured to represent the Corridor
   topology and shall train using the PPO algorithm via Stable Baselines3.
6. WHEN the MARL_Scheduler cannot produce any conflict-free rescheduling proposal within the
   30-second window, THE MARL_Scheduler SHALL emit a `NO_FEASIBLE_PROPOSAL` event to the
   Operations_Controller within 35 seconds of receiving the disruption event, indicating that
   the disruption scenario requires manual intervention.

---

### Requirement 8: Digital Twin Visualization

**User Story:** As an Operations_Controller, I want a live GIS-based visualization of the Corridor
showing train positions, sensor alerts, and defect detections, so that situational awareness is
available at a glance without consulting multiple separate dashboards.

#### Acceptance Criteria

1. THE Digital_Twin SHALL render real-time train positions on a GIS corridor map with a position
   refresh rate of at most 5 seconds.
2. WHEN a train position has not been updated for more than 10 seconds, THE Digital_Twin SHALL
   display a staleness indicator on that train's marker until a fresh position is received.
3. WHEN a `DEFECT_ALERT` event is received, THE Digital_Twin SHALL attempt to display a
   geo-located marker at the defect coordinate within 3 seconds of the event timestamp; WHEN
   the marker cannot be rendered due to a system failure, THE Digital_Twin SHALL relay the
   `DEFECT_ALERT` to the operations notification channel to ensure the alert is not silently lost.
4. WHEN a `MAINTENANCE_ADVISORY` event is received, THE Digital_Twin SHALL highlight the affected
   asset on the map and display the failure-probability score and 72-hour horizon label.
5. WHEN the Delay_Predictor produces a new forecast, THE Digital_Twin SHALL update the colour-coded
   delay overlay on affected train markers within 3 seconds of receiving the forecast payload.
6. THE Digital_Twin SHALL remain usable on a standard 1920×1080 operations workstation display at
   a sustained frame rate of at least 30 fps when rendering up to 200 concurrent train positions.
7. WHEN a `KAVACH_ADVISORY` event is received from the Kavach_Advisory_Layer, THE Digital_Twin
   SHALL display the advisory braking curve recommendation in a read-only panel without overlaying
   it on the certified Kavach 4.0 display.

---

### Requirement 9: Cybersecurity Monitoring Dashboard

**User Story:** As a security officer, I want continuous monitoring of simulated SCADA traffic for
anomalous patterns, so that potential intrusion attempts on railway control systems can be detected
and escalated to human reviewers before damage occurs.

#### Acceptance Criteria

1. THE Cybersecurity_Dashboard SHALL classify simulated SCADA network traffic as normal or anomalous
   using an LSTM autoencoder model, evaluating each 60-second traffic window on a rolling basis
   with a stride of 10 seconds so that consecutive windows overlap by 50 seconds.
2. WHEN the LSTM autoencoder reconstruction error for a traffic window exceeds the configured
   threshold, THE Cybersecurity_Dashboard SHALL emit a `SECURITY_ANOMALY` alert identifying the
   IEC 62443 zone, timestamp, and reconstruction error value.
3. THE Cybersecurity_Dashboard SHALL NOT autonomously modify firewall rules or access controls on
   Zone_3/4_Systems in response to any detected anomaly.
4. WHEN a `SECURITY_ANOMALY` alert is emitted, THE Cybersecurity_Dashboard SHALL require
   acknowledgement by an authorized security officer before the alert is cleared.
5. WHEN a `SECURITY_ANOMALY` alert has not been acknowledged within 15 minutes of emission,
   THE Cybersecurity_Dashboard SHALL escalate the alert to the next authorized security officer
   in the on-call roster and log the escalation event with a timestamp.
6. THE Cybersecurity_Dashboard SHALL display the current security posture of each IEC 62443 zone
   as a colour-coded status panel (green / amber / red) updated within 10 seconds of any zone
   state change.
7. THE Cybersecurity_Dashboard SHALL retain all `SECURITY_ANOMALY` events and officer
   acknowledgements in an append-only audit log from which no entry may be deleted or modified,
   for a minimum of 365 days.

---

### Requirement 10: Kavach++ Advisory Layer

**User Story:** As an Operations_Controller, I want ML-enhanced braking curve recommendations
derived from Kavach 4.0 data, so that I can evaluate whether the certified Kavach response is
conservative or marginal for current track conditions, without any risk to the certified safety logic.

#### Acceptance Criteria

1. THE Kavach_Advisory_Layer SHALL consume read-only data from the Kavach 4.0 data interface and
   SHALL NOT write to, modify, or interrupt any Kavach 4.0 data bus or control channel.
2. WHEN the Kavach_Advisory_Layer produces a braking curve recommendation, THE Kavach_Advisory_Layer
   SHALL label the output explicitly as "ADVISORY — NOT CERTIFIED" in both the payload metadata and
   the Digital_Twin display panel.
3. THE Kavach_Advisory_Layer SHALL produce advisory braking curves whose computed stopping distance
   at any given speed is equal to or greater than the stopping distance of the certified Kavach 4.0
   curve at the same speed and track conditions, ensuring the advisory is never less conservative
   than the certified logic.
4. IF sensor data required to compute the advisory braking curve is unavailable, THEN THE
   Kavach_Advisory_Layer SHALL withhold the advisory and display a `KAVACH_ADVISORY_UNAVAILABLE`
   status rather than producing a curve based on incomplete inputs.
5. THE Kavach_Advisory_Layer SHALL be deployed in a network segment that has no write access to
   Zone_3/4_Systems, enforced at the network layer and verified by the IEC 62443 zone architecture.

---

### Requirement 11: Model Governance and Auditability

**User Story:** As a safety officer, I want all ML model versions deployed in RailOS to be versioned,
logged, and auditable, so that any advisory output can be traced to the exact model that produced it.

#### Acceptance Criteria

1. THE RailOS SHALL assign a unique version identifier in MAJOR.MINOR.PATCH semantic versioning
   format to each trained model artifact before deployment to any Edge_Node or central inference
   service.
2. WHEN an inference result is produced by any ML component, THE RailOS SHALL record the model
   version identifier, a hash of the input feature vector, the scalar or structured output value
   (excluding raw sensor payloads), and the UTC timestamp in the audit log.
3. THE RailOS SHALL support rollback of any deployed model to the previous version within 15 minutes
   of an authorized rollback request, without requiring an Edge_Node restart; WHEN a rollback
   operation has not completed within 15 minutes, THE RailOS SHALL abort the rollback, restore the
   last known stable model state, and emit a `ROLLBACK_TIMEOUT` alert to the engineering team;
   IF no previous version exists for a given model, THE RailOS SHALL reject the rollback request
   immediately with a `NO_PREVIOUS_VERSION` error.
4. WHEN a model is updated on an Edge_Node via the Federated_Learning_Layer, THE RailOS SHALL
   record the source aggregation round identifier and the pre-update and post-update model version
   identifiers in the audit log.
5. THE RailOS SHALL retain model audit log entries for a minimum of 365 days.

---

### Requirement 12: Human-in-the-Loop Authorization

**User Story:** As a safety officer, I want all safety-affecting advisory outputs from RailOS to
require explicit human authorization before any downstream action is taken, so that no ML component
can trigger operational changes autonomously.

#### Acceptance Criteria

1. THE RailOS SHALL classify every advisory output as requiring Operations_Controller authorization
   before it is forwarded to any operational system or maintenance dispatch workflow.
2. WHEN an advisory output is produced, THE RailOS SHALL display it to the Operations_Controller
   with an "Authorize" button and a "Reject" button rendered at a minimum size of 44×44 CSS pixels
   and visually distinct from surrounding UI elements, and SHALL NOT forward the advisory until one
   of these actions is taken.
3. IF an advisory output has not been acted upon within 10 minutes of display, THEN THE RailOS
   SHALL escalate the pending advisory to a secondary authorized Operations_Controller; IF no
   secondary Operations_Controller is available, THE RailOS SHALL emit a `ESCALATION_FAILED` alert
   to the operations supervisor channel and retain the advisory in pending state.
4. THE RailOS SHALL log every authorization and rejection event with the Operations_Controller
   identity, timestamp, advisory identifier, and action taken; pending advisory states SHALL NOT
   be logged until a final authorize or reject decision is recorded.
5. THE RailOS SHALL NOT issue any command to a Zone_3/4_System under any circumstances, including
   when an advisory has been authorized by an Operations_Controller; all Zone_3/4_System
   interactions remain exclusively under direct human or certified Kavach 4.0 control.

---

### Requirement 13: Data Privacy and Locality

**User Story:** As a data governance officer, I want raw sensor data to remain within the zone where
it is collected, so that regulatory data locality requirements are met and no raw operational data
is centralized outside its source zone.

#### Acceptance Criteria

1. THE Federated_Learning_Layer SHALL transmit only model weight gradients or weight deltas between
   zones; raw sensor time-series data SHALL NOT leave the Edge_Node on which it was recorded.
2. THE RailOS SHALL apply differential privacy noise (Gaussian mechanism, configurable noise
   multiplier σ ≥ 0.1) to all gradient transmissions from Edge_Nodes to the aggregation server.
3. WHEN data collected in one zone is required for cross-zone analytics, THE RailOS SHALL use only
   aggregated statistics or summaries from which individual asset identifiers and raw timestamps
   have been removed, and SHALL NOT transmit raw event records across zone boundaries.
4. WHEN an authorized data governance officer requests a data lineage report for a stored dataset,
   THE RailOS SHALL produce a report identifying the source Edge_Node identifier, the collection
   timestamp range, and all transformations applied to the data since collection.

---

### Requirement 14: Performance Benchmarking and Regression Testing

**User Story:** As a development engineer, I want automated performance benchmarks run against each
model before deployment, so that regressions in accuracy or latency are caught before they affect
operations.

#### Acceptance Criteria

1. THE RailOS SHALL execute a benchmark suite against every candidate model artifact before it is
   approved for deployment; for the Defect_Detector the primary metrics are precision and recall
   per Defect_Category and inference latency in milliseconds; for the Predictive_Maintenance_Engine
   the primary metrics are failure-probability calibration error and confidence interval coverage;
   for the Delay_Predictor the primary metric is mean absolute error in minutes; for the
   MARL_Scheduler the primary metrics are Conflict-free proposal rate and 30-second proposal
   generation rate.
2. WHEN a candidate model's benchmark result is worse than the currently deployed model's benchmark
   result on any primary metric defined in criterion 1 by more than 5% relative to the deployed
   model's value on that metric, THE RailOS SHALL block deployment and emit a `REGRESSION_DETECTED`
   alert to the responsible engineering team identifying the metric name, the deployed value, and
   the candidate value.
3. THE Defect_Detector benchmark SHALL use a held-out test split containing at least 500 labelled
   images per Defect_Category to produce statistically reliable precision and recall estimates.
4. THE Predictive_Maintenance_Engine benchmark SHALL include test cases with DATA_QUALITY flag
   values of 0%, 20%, and 40% interpolation to verify that confidence intervals widen
   monotonically and satisfy the ratio specified in Requirement 4 criterion 6.
5. THE MARL_Scheduler benchmark SHALL include at least 1,000 simulated disruption episodes per
   evaluation run to verify the Conflict-free invariant across a statistically representative set
   of scenarios.

---

### Requirement 15: System Availability and Reliability

**User Story:** As an Operations_Controller, I want RailOS to maintain high availability during
operational periods, so that advisory services are not interrupted during active corridor operations.

#### Acceptance Criteria

1. THE RailOS SHALL maintain a service availability of at least 99.95% across all non-maintenance
   operational periods, corresponding to no more than 4.38 hours of unplanned downtime per year;
   availability SHALL be computed excluding scheduled maintenance windows.
2. WHEN any single non-safety-critical subsystem fails, THE RailOS SHALL continue operating all
   remaining subsystems without cascading interruption to corridor advisory services.
3. THE RailOS SHALL schedule planned maintenance windows exclusively outside peak operational hours
   and SHALL announce each maintenance window to Operations_Controllers at least 24 hours in
   advance.
4. WHEN a subsystem becomes unavailable, THE RailOS SHALL degrade functionality gracefully such
   that the Digital_Twin and all alert channels remain active and visible to the
   Operations_Controller even when ML inference subsystems are offline.

---

### Requirement 16: Disaster Recovery

**User Story:** As an Engineering_Team member, I want RailOS to recover from catastrophic
infrastructure failures within defined time objectives, so that corridor operations can resume
without prolonged outages.

#### Acceptance Criteria

1. THE RailOS SHALL support restoration of operational databases from the most recent backup within
   30 minutes of a catastrophic failure event (Recovery Time Objective ≤ 30 minutes).
2. THE RailOS SHALL replicate all operational data — including sensor streams, audit logs, and model
   artifacts — to at least one geographically separated storage node with a maximum replication lag
   of 60 seconds (Recovery Point Objective ≤ 60 seconds).
3. WHEN central infrastructure becomes unavailable, Edge_Nodes SHALL support corridor-level degraded
   autonomous operation for a minimum of 24 hours using locally buffered data and locally stored
   model artifacts.
4. THE RailOS SHALL execute automated backup integrity checks at least once per 24-hour period;
   WHEN any backup integrity check fails, THE RailOS SHALL emit a `BACKUP_INTEGRITY_FAILURE` alert
   to the engineering monitoring channel identifying the affected backup identifier and the check
   failure reason.

---

### Requirement 17: Observability and Telemetry

**User Story:** As an Engineering_Team member, I want comprehensive telemetry, tracing, and
structured logging across all RailOS subsystems, so that system health can be monitored in real
time and incidents can be diagnosed efficiently.

#### Acceptance Criteria

1. THE RailOS SHALL expose Prometheus-compatible metrics endpoints for all critical subsystems,
   including Data_Pipeline ingestion throughput, Edge_Node inference latency, Federated_Learning_Layer
   round durations, and MARL_Scheduler proposal generation times.
2. THE RailOS SHALL support end-to-end distributed tracing compatible with the OpenTelemetry
   specification across the Data_Pipeline, Edge_Nodes, and all AI inference components, with trace
   context propagated across all service boundaries.
3. THE RailOS SHALL generate structured JSON logs for all operational events, including sensor
   ingestion events, ML inference results, advisory outputs, authorization actions, and error
   conditions.
4. WHEN any subsystem's error rate exceeds 1% of requests over a 5-minute rolling window, THE
   RailOS SHALL emit a `SUBSYSTEM_DEGRADED` alert to the engineering monitoring channel identifying
   the subsystem name, the measured error rate, and the window start and end timestamps.
5. THE RailOS SHALL retain telemetry data for a minimum of 30 days to support post-incident
   analysis.

---

### Requirement 18: Explainable AI

**User Story:** As an Operations_Controller and safety officer, I want ML advisory outputs to include
human-readable explanations of the primary factors driving each advisory, so that I can evaluate
whether to authorize or reject an advisory with informed judgment.

#### Acceptance Criteria

1. WHEN any ML component (Defect_Detector, Predictive_Maintenance_Engine, Delay_Predictor,
   MARL_Scheduler, or Kavach_Advisory_Layer) produces an advisory output, THE RailOS SHALL include
   a feature attribution explanation identifying the top 3 input features by contribution magnitude
   that most influenced the output.
2. THE Defect_Detector SHALL generate a Grad-CAM or equivalent spatial localization overlay for
   each detected defect, highlighting the image region that contributed most to the classification;
   this overlay SHALL be included in the `DEFECT_ALERT` payload or be retrievable by alert
   identifier.
3. THE RailOS SHALL express all feature attribution explanations in plain-language railway domain
   terminology (for example, "high vibration amplitude on left rail" or "40-minute compound delay
   on adjacent track segment") rather than raw feature indices or model-internal identifiers.
4. WHEN an ML component produces a feature attribution explanation, THE RailOS SHALL produce that
   explanation within the same latency budget as the primary inference output such that adding
   attribution SHALL NOT cause the subsystem to exceed its defined latency SLA.

---

### Requirement 19: Fairness and Bias Monitoring

**User Story:** As a safety officer, I want continuous monitoring of model performance consistency
across varying operational conditions, so that predictive models do not systematically underperform
for specific infrastructure regions, weather conditions, or time periods.

#### Acceptance Criteria

1. THE RailOS SHALL partition the held-out evaluation dataset for each deployed ML model into at
   least three operational strata: weather condition (clear, rain, fog), time-of-day period
   (day: 06:00–22:00 local time, night: 22:00–06:00 local time), and infrastructure region
   (each distinct corridor division or segment).
2. THE RailOS SHALL ensure that model performance on any single stratum does not degrade by more
   than 10% relative to the overall baseline metric for that model; WHEN a stratum-level metric
   falls more than 10% below the baseline (for example, below 82.8% when the overall precision
   baseline is 92%), THE RailOS SHALL treat that as a bias threshold violation.
3. WHEN stratum-level degradation exceeds the 10% threshold during a benchmark run, THE RailOS
   SHALL block deployment of that model and emit a `BIAS_THRESHOLD_EXCEEDED` alert identifying the
   affected model identifier, stratum name, and measured metric value.
4. THE RailOS SHALL re-execute the fairness evaluation whenever a model is updated via the
   Federated_Learning_Layer or direct retraining before the updated model is approved for
   deployment.

---

### Requirement 20: Model Drift Detection

**User Story:** As an Engineering_Team member, I want continuous monitoring of deployed ML model
inference distributions for drift relative to training baselines, so that degraded model performance
caused by data distribution shift is detected before it affects operational quality.

#### Acceptance Criteria

1. THE RailOS SHALL compute a distribution drift score using Population Stability Index or an
   equivalent statistical measure for each deployed ML model on a rolling 24-hour window of
   inference inputs, compared against the training data distribution baseline established at
   deployment time.
2. WHEN the drift score for any model exceeds the configured threshold (default PSI ≥ 0.2) for 3
   consecutive daily windows, THE RailOS SHALL flag the model as `DRIFT_DETECTED`, emit a
   `MODEL_DRIFT_ALERT` to the Engineering_Team identifying the model identifier and measured drift
   score, and apply a `DRIFT_WARNING` flag to all advisory outputs produced by the flagged model
   until retraining is completed and the drift score returns below threshold.
3. WHEN an advisory output carries a `DRIFT_WARNING` flag, THE RailOS SHALL surface the flag as a
   visible indicator alongside the advisory on the Operations_Controller's display, prompting
   heightened review scrutiny before authorization.
4. THE RailOS SHALL retain the drift score history for each model for a minimum of 90 days to
   support trend analysis.

---

### Requirement 21: Digital Twin State Consistency

**User Story:** As an Operations_Controller, I want the Digital Twin to accurately reflect the
real-world Corridor state at all times, so that situational awareness is never based on stale or
contradictory data.

#### Acceptance Criteria

1. THE Digital_Twin SHALL reflect train position updates, sensor alerts, and advisory events within
   5 seconds of their occurrence in the source system, maintaining state synchronization accuracy
   within ±5 seconds of real-world operational events.
2. WHEN the Digital_Twin receives an infrastructure state update that conflicts with its current
   state model — including a train position that violates physical track topology or two trains
   assigned to the same track segment — THE Digital_Twin SHALL reject the conflicting update, log
   the inconsistency with the source event identifier and timestamp, and retain the last valid
   state.
3. WHEN the Digital_Twin has not received a state update for any tracked entity for more than 10
   seconds, THE Digital_Twin SHALL display a staleness indicator for that entity until a fresh
   update is received.
4. THE Digital_Twin state store SHALL propagate each state change to all connected visualization
   clients within 2 seconds of the change occurring (eventual consistency window).

---

### Requirement 22: Energy Efficiency

**User Story:** As an Engineering_Team member aligned with Indian Railways' sustainability goals,
I want Edge_Nodes to minimize power consumption during low-load periods and the system to report
corridor energy metrics, so that operational sustainability is measurable and improvable.

#### Acceptance Criteria

1. WHEN an Edge_Node's average inference request rate falls below 10% of its rated capacity for 5
   consecutive minutes, THE Edge_Node SHALL reduce active inference threads and apply adaptive
   power management to reduce power consumption by at least 20% relative to full-load operation.
2. THE RailOS SHALL estimate and report corridor-level operational energy efficiency metrics
   (inference operations per watt-hour) for each Edge_Node on a 24-hour rolling basis, accessible
   via the observability telemetry endpoint defined in Requirement 17.
3. WHEN a new inference request arrives at an Edge_Node that is in a reduced-power state, THE
   Edge_Node SHALL restore full inference capacity within 500 ms of request receipt, ensuring that
   power management actions do not cause the Edge_Node to exceed its defined inference latency
   SLAs.

---

### Requirement 23: Role-Based Access Control

**User Story:** As a Security_Officer, I want all RailOS interfaces to enforce role-based access
control so that each user role can only perform actions within its authorization scope.

#### Acceptance Criteria

1. THE RailOS SHALL enforce RBAC for four named roles with the following permission scopes:
   Operations_Controller (view advisories, authorize and reject advisories, view Digital_Twin),
   Security_Officer (view and acknowledge security anomalies, view audit logs),
   Engineering_Team (deploy and rollback models, view benchmarks, configure drift thresholds),
   and Governance_Officer (request data lineage reports, configure retention policies).
2. WHEN a user attempts an action outside their assigned role's permission scope, THE RailOS SHALL
   deny the action, return an authorization error to the user identifying the denied action, and
   log the unauthorized access attempt with the user identity, attempted action, and timestamp.
3. THE RailOS SHALL require MFA for all privileged operational accounts covering all roles except
   read-only observer accounts.
4. THE RailOS SHALL manage role assignments through a centralized identity management system;
   no role SHALL be able to modify its own or another role's assignments through any RailOS
   interface.

---

### Requirement 24: API Standards and Authentication

**User Story:** As an Engineering_Team member, I want all RailOS subsystem interfaces to follow
consistent API standards with authenticated access, so that subsystem interoperability and external
integration are reliable and secure.

#### Acceptance Criteria

1. THE RailOS SHALL expose REST (HTTP/1.1 and HTTP/2) and gRPC interfaces for all subsystem
   operations that require external or inter-service access.
2. WHEN an API request arrives at any RailOS interface without a valid bearer token issued by the
   RailOS identity provider (OAuth 2.0 / JWT), THE RailOS SHALL reject the request with HTTP 401
   and SHALL NOT process the request.
3. WHEN an authenticated client exceeds 1,000 requests per minute to any external RailOS API
   interface, THE RailOS SHALL return HTTP 429 with a `Retry-After` header indicating the earliest
   time at which the client may retry.
4. THE RailOS SHALL version all API interfaces using a path-based scheme (for example, `/api/v1/`)
   and SHALL maintain backward compatibility within a major version; breaking changes SHALL require
   a new major version before the changed interface is exposed.

---

### Requirement 25: End-to-End Alert Latency

**User Story:** As an Operations_Controller, I want critical advisory alerts to be delivered from
sensor detection to my dashboard within a defined end-to-end latency budget, so that I have
sufficient time to respond before operational safety margins are affected.

#### Acceptance Criteria

1. THE RailOS SHALL deliver critical advisory alerts — including `DEFECT_ALERT`,
   `MAINTENANCE_ADVISORY`, `SECURITY_ANOMALY`, and `NO_FEASIBLE_PROPOSAL` — from sensor event
   ingestion at the Edge_Node to visualization on the Operations_Controller's Digital_Twin display
   within 5 seconds under nominal corridor load (up to 200 active train positions and up to 50
   concurrent sensor feeds).
2. WHEN end-to-end alert delivery latency exceeds 5 seconds for any critical alert, THE RailOS
   SHALL log the latency breach with the alert identifier, the measured latency in milliseconds,
   and the pipeline stage that introduced the delay.
3. THE RailOS SHALL measure and report end-to-end alert delivery latency as a Prometheus metric
   at the p50, p95, and p99 percentiles on a 1-minute rolling basis.

---

### Requirement 26: Digital Forensics

**User Story:** As a Security_Officer, I want raw anomaly evidence preserved in tamper-resistant
storage so that forensic investigations can be conducted after security incidents.

#### Acceptance Criteria

1. WHEN a `SECURITY_ANOMALY` alert is emitted, THE RailOS SHALL capture and preserve the raw
   60-second SCADA traffic window that triggered the alert, the LSTM autoencoder reconstruction
   error vector, and all associated metadata (IEC 62443 zone identifier, timestamp, and threshold
   value) in forensic storage.
2. THE RailOS SHALL store all forensic evidence in append-only, tamper-resistant storage using
   cryptographic chaining or WORM-equivalent mechanisms from which no entry may be deleted,
   modified, or overwritten.
3. THE RailOS SHALL retain forensic evidence records for a minimum of 365 days.
4. WHEN an authorized Security_Officer requests a forensic evidence package for a specific alert
   identifier, THE RailOS SHALL produce a downloadable archive containing the preserved traffic
   window, reconstruction error data, alert metadata, and all audit log entries associated with
   that alert within 5 minutes of the request being submitted.

---

### Requirement 27: Time Synchronization

**User Story:** As an Engineering_Team member, I want all RailOS subsystems to maintain synchronized
clocks relative to a trusted UTC source, so that sensor timestamps, audit log entries, and
distributed trace spans are globally consistent and can be correlated across subsystems.

#### Acceptance Criteria

1. All RailOS subsystems — including the Data_Pipeline, Edge_Nodes, zone compute nodes, and central
   servers — SHALL synchronize their system clocks against a trusted UTC time source using PTP
   (IEEE 1588) or GPS-disciplined NTP, with maximum clock drift not exceeding ±100 ms from the
   UTC reference at any time during normal operation.
2. WHEN an Edge_Node's clock drift exceeds ±100 ms relative to the UTC reference, THE Edge_Node
   SHALL emit a `CLOCK_DRIFT_ALERT` to the monitoring topic and apply a clock correction; WHEN the
   drift cannot be corrected because the time source is unreachable, THE Edge_Node SHALL tag all
   subsequently generated events with a `CLOCK_UNRELIABLE` flag until clock synchronization is
   restored.
3. THE Data_Pipeline SHALL derive sensor event timestamps from the originating Edge_Node's
   synchronized clock rather than from the Data_Pipeline receipt time, so that the original
   physical event ordering is preserved.

---

### Requirement 28: Data Retention Lifecycle

**User Story:** As a Governance_Officer, I want RailOS operational data to be automatically archived
or purged according to configurable retention policies, so that storage costs are controlled and
data governance obligations are met.

#### Acceptance Criteria

1. THE RailOS SHALL support configurable retention policies for each data category with the
   following defaults: raw sensor events (90 days), inference audit logs (365 days), security
   anomaly records (365 days), forensic evidence (365 days), telemetry metrics (30 days), and
   model artifacts (retain all versions indefinitely until explicit deletion by an
   Engineering_Team member).
2. WHEN a data record reaches the end of its configured retention period, THE RailOS SHALL either
   archive it to cold storage or purge it according to the policy configured for that data
   category; THE RailOS SHALL NOT purge any record that is subject to an active forensic hold.
3. THE RailOS SHALL produce a monthly data retention compliance report identifying: total records
   archived and purged per category, any records that exceeded their retention period without
   being processed, and the current storage consumption per category.
4. WHEN a Governance_Officer places a forensic hold on a specific alert identifier or time range,
   THE RailOS SHALL prevent automatic purging of all data records associated with that hold until
   the hold is explicitly released by an authorized Governance_Officer.

---

### Requirement 29: Operator Alert Fatigue Management

**User Story:** As an Operations_Controller, I want the advisory system to prioritize and suppress
redundant alerts, so that I can focus on actionable advisories without being overwhelmed by
duplicate or low-priority notifications.

#### Acceptance Criteria

1. THE RailOS SHALL assign each advisory output a severity level — CRITICAL, HIGH, MEDIUM, or LOW
   — based on the originating subsystem and the confidence or probability score, and SHALL present
   advisories to the Operations_Controller in severity-descending order in the display queue.
2. WHEN two or more `DEFECT_ALERT` events are emitted for the same GPS coordinate within a 50-metre
   radius and the same Defect_Category within a configurable suppression window (default 10
   minutes), THE RailOS SHALL suppress the duplicate alerts and increment a suppression counter on
   the original alert rather than generating separate advisory display entries.
3. WHEN a `MAINTENANCE_ADVISORY` is emitted for an asset that already has an active unresolved
   advisory, THE RailOS SHALL update the existing advisory's probability score and timestamp rather
   than creating a new advisory entry for that asset.
4. THE RailOS SHALL display the count of currently suppressed duplicates for each active advisory
   so that the Operations_Controller is informed of the suppression state at all times.

---

### Requirement 30: Ethical AI Constraints

**User Story:** As a safety officer, I want the system to enforce architectural constraints that
prevent any ML component from executing safety-critical decisions autonomously, so that human
oversight is structurally guaranteed rather than relying on software configuration.

#### Acceptance Criteria

1. THE RailOS SHALL enforce a mandatory human authorization gate in the advisory forwarding pathway
   such that no advisory output can reach any operational system or maintenance dispatch workflow
   without a recorded authorize action from an Operations_Controller; this constraint SHALL be
   implemented as a structural architectural boundary and SHALL NOT be configurable or bypassable
   through any system setting or API call.
2. THE RailOS SHALL prohibit all ML components from initiating, modifying, or cancelling any
   operational command directed at a Zone_3/4_System, regardless of advisory authorization state.
3. WHEN the human authorization gate component becomes unavailable, THE RailOS SHALL hold all
   pending advisories in a queue and SHALL NOT forward any advisory to any downstream system until
   the gate is restored and an Operations_Controller has reviewed the queued items.
4. THE RailOS SHALL include the authorization gate status — operational, degraded, or unavailable
   — as a first-class Prometheus metric and SHALL display this status visibly on the Digital_Twin
   dashboard at all times.

---

### Requirement 31: Legacy System Integration

**User Story:** As an Engineering_Team member, I want RailOS to integrate with Indian Railways'
existing operational systems through adapter interfaces, so that existing data sources (NTES, OMRS,
WILD, Electronic Interlocking) can be consumed without requiring modifications to those systems.

#### Acceptance Criteria

1. THE RailOS SHALL provide adapter interfaces for NTES (train position and delay REST API), OMRS
   (rolling stock monitoring data stream), and WILD (wheel impact load data stream) that translate
   each system's native data format into the RailOS canonical sensor schema without requiring any
   modification to the source system.
2. WHEN a legacy system adapter fails to produce a valid canonical event after 3 consecutive parse
   attempts for the same source payload, THE RailOS SHALL emit a `LEGACY_ADAPTER_FAILURE` alert
   identifying the source system name and the error reason, and route the raw payload to the
   dead-letter Kafka topic.
3. THE RailOS SHALL deploy each legacy adapter as an independently replaceable component such that
   replacing one adapter does not require a restart of the core Data_Pipeline.
4. THE RailOS SHALL record the software version of each connected legacy system adapter in the
   telemetry system so that adapter compatibility can be tracked across upgrades.

---

### Requirement 32: Simulation Validation

**User Story:** As an Engineering_Team member, I want Digital Twin simulation outputs and
MARL_Scheduler proposals to be validated against historical operational data before deployment,
so that simulation fidelity is verified before the system is used for operational advisory purposes.

#### Acceptance Criteria

1. THE Digital_Twin simulation engine SHALL be validated against a held-out set of historical IR
   operational data covering a minimum of 30 days of actual train movement records before
   deployment; simulated train positions SHALL match historical positions with a mean absolute
   position error of no more than 500 metres at any point in the trajectory.
2. THE MARL_Scheduler SHALL be evaluated on a set of at least 100 historical disruption scenarios
   reconstructed from NTES historical data; the proportion of scenarios for which the
   MARL_Scheduler produces a conflict-free proposal within 30 seconds SHALL be at least 70%.
3. THE RailOS SHALL record all simulation validation results in the model governance audit log with
   the dataset identifier, evaluation date, and pass or fail status for each metric before the
   simulation engine or MARL_Scheduler component is approved for deployment.

---

### Requirement 33: Network Partition Tolerance

**User Story:** As an Operations_Controller, I want Edge_Nodes to maintain local operational
continuity when network partitions occur, so that station-level situational awareness and inference
are preserved even when the corridor network is segmented.

#### Acceptance Criteria

1. WHEN an Edge_Node detects a network partition — defined as 3 consecutive failed heartbeats
   within a 30-second window, consistent with Requirement 2 criterion 1 — THE Edge_Node SHALL
   continue operating in autonomous mode with no dependency on central coordination for local
   inference or alerting.
2. WHEN a network partition separates two or more Edge_Nodes from each other but leaves each
   Edge_Node connected to the central Data_Pipeline, each Edge_Node SHALL continue publishing
   events to the central Data_Pipeline independently; THE Data_Pipeline SHALL merge incoming
   event streams by sensor-event timestamp and deduplicate events by event identifier.
3. WHEN a network partition is resolved, THE RailOS SHALL reconcile any divergent state between
   Edge_Nodes and the central Data_Pipeline using sensor-event timestamp ordering without
   discarding events from either side of the partition.

---

### Requirement 34: Human Factors and Operator Interface

**User Story:** As an Operations_Controller working under high cognitive load, I want the RailOS
interface to present information using standardized railway terminology, consistent visual
hierarchy, and accessibility-compliant design, so that I can accurately interpret and act on
advisories under time pressure.

#### Acceptance Criteria

1. THE RailOS SHALL present all operational advisories using standardized Indian Railways
   operational terminology as defined in the IR Operations Manual, with colour-coded severity
   levels: RED for CRITICAL, AMBER for HIGH, YELLOW for MEDIUM, and BLUE for LOW.
2. THE Digital_Twin dashboard SHALL comply with WCAG 2.1 Level AA accessibility standards for
   colour contrast, text sizing, and keyboard navigability.
3. THE RailOS SHALL present no more than 5 simultaneous advisory notifications in the primary
   alert panel; WHEN more than 5 advisories are active, THE RailOS SHALL display the top 5 by
   severity and provide a scrollable queue for the remainder with the total queue count visible
   at all times.
4. All interactive controls on the Operations_Controller interface — including Authorize, Reject,
   Acknowledge, and Escalate actions — SHALL have a minimum touch and click target size of 44×44
   CSS pixels and SHALL be visually distinguishable from non-interactive elements by both colour
   and shape or border.
5. THE RailOS SHALL support a high-contrast display mode and a reduced-motion mode for operators
   with visual sensitivity; both modes SHALL be accessible from the dashboard settings without
   requiring a session restart.

---

### Requirement 35: Safety Evidence Traceability

**User Story:** As a safety officer, I want RailOS to maintain explicit traceability links between requirements, hazards, mitigations, verification evidence, and deployed subsystem versions, so that the safety case for each deployed component can be reconstructed and audited at any time.

#### Acceptance Criteria

1. THE RailOS SHALL maintain a traceability matrix linking each functional requirement identifier to the hazard identifiers it mitigates, the verification evidence records that demonstrate compliance, and the deployed subsystem version under which the evidence was collected.
2. WHEN a subsystem is deployed at a new version, THE RailOS SHALL update the traceability matrix to associate the new version identifier with any new or updated verification evidence produced during the benchmark and validation run for that version.
3. WHEN an Engineering_Team member or safety officer requests a traceability report for a specific subsystem version, THE RailOS SHALL produce a structured report in JSON or PDF format within 5 minutes, listing all linked requirements, hazards, mitigations, and evidence records for that version.
4. THE RailOS SHALL retain all traceability matrix records for a minimum of 365 days and SHALL NOT allow any traceability record to be deleted once created; corrections SHALL be recorded as new records linked to the superseded record.

---

### Requirement 36: Hazard Register

**User Story:** As a safety officer, I want a maintained hazard register identifying operational hazards, mitigation strategies, residual risk classifications, and approval status, so that the operational risk posture of the RailOS pilot is visible and governable.

#### Acceptance Criteria

1. THE RailOS SHALL maintain a hazard register containing at minimum the following fields per entry: hazard identifier, hazard description, affected subsystem, likelihood classification (Low / Medium / High), severity classification (Minor / Major / Catastrophic), residual risk classification after mitigation, mitigation strategy description, verification evidence reference, and approval status (Open / Mitigated / Accepted / Closed).
2. WHEN a new operational anomaly pattern is detected — including repeated `MODEL_DRIFT_ALERT`, `BIAS_THRESHOLD_EXCEEDED`, `LEGACY_ADAPTER_FAILURE`, or `BACKUP_INTEGRITY_FAILURE` events — THE RailOS SHALL flag the pattern for hazard register review and emit a `HAZARD_REVIEW_REQUIRED` notification to the Engineering_Team and safety officer.
3. THE hazard register SHALL be accessible to Safety_Officer and Engineering_Team roles and SHALL NOT be modifiable by Operations_Controller or Governance_Officer roles.
4. THE RailOS SHALL retain all hazard register entries and their revision history for a minimum of 365 days.

---

### Requirement 37: Configuration Management

**User Story:** As an Engineering_Team member, I want all operational configurations, thresholds, suppression windows, and model deployment parameters to be versioned with an immutable change history, so that any configuration state that produced an advisory output can be reconstructed precisely.

#### Acceptance Criteria

1. THE RailOS SHALL assign a version identifier to every configuration artifact — including alert thresholds, suppression windows, drift PSI thresholds, rate limits, retention policy values, and model deployment parameters — before the configuration is applied to any running subsystem.
2. WHEN a configuration value is changed, THE RailOS SHALL record an immutable change log entry containing the configuration key, the previous value, the new value, the identity of the user who made the change, and the UTC timestamp; no change log entry SHALL be modifiable or deletable after creation.
3. THE RailOS SHALL retain configuration change history for a minimum of 365 days.
4. WHEN an inference audit log record references a specific inference event, the configuration version active at the time of that event SHALL be recoverable from the change log by cross-referencing the event UTC timestamp.

---

### Requirement 38: Supply Chain Security

**User Story:** As a Security_Officer, I want all third-party model artifacts, container images, and software dependencies to be cryptographically verified before deployment, and a Software Bill of Materials maintained for each release, so that supply chain integrity is continuously assured.

#### Acceptance Criteria

1. THE RailOS SHALL verify the cryptographic signature or SHA-256 checksum of every third-party model artifact, container image, and software dependency package before deployment; WHEN verification fails, THE RailOS SHALL block deployment and emit a `SUPPLY_CHAIN_INTEGRITY_FAILURE` alert identifying the artifact name, expected checksum, and observed checksum.
2. THE RailOS SHALL generate a Software Bill of Materials (SBOM) in CycloneDX or SPDX format for each deployment release, listing all included software components, their versions, and their verified checksums.
3. THE RailOS SHALL retain the SBOM for each deployment release for a minimum of 365 days.
4. WHEN a newly published Common Vulnerability and Exposure (CVE) affects a component listed in the active SBOM, THE RailOS SHALL emit a `CVE_ALERT` to the Engineering_Team within 24 hours of the CVE being added to the National Vulnerability Database (NVD) feed.

---

### Requirement 39: Container Security

**User Story:** As a Security_Officer, I want all RailOS subsystem containers to execute with least-privilege permissions and have their runtime anomalies monitored, so that the blast radius of any container compromise is minimized.

#### Acceptance Criteria

1. THE RailOS SHALL execute all subsystem containers with read-only root filesystems where operationally feasible; WHEN a subsystem requires write access to its root filesystem, THE Engineering_Team SHALL document the justification in the hazard register as a residual risk acceptance.
2. THE RailOS SHALL enforce least-privilege container permissions by prohibiting privileged mode execution and dropping all Linux capabilities not explicitly required by the subsystem's documented operational function.
3. THE RailOS SHALL monitor container runtime behaviour for privilege escalation attempts; WHEN a privilege escalation attempt is detected in any container, THE RailOS SHALL emit a `PRIVILEGE_ESCALATION_ALERT` to the Security_Officer, log the container name, timestamp, and attempted capability, and terminate the affected container within 30 seconds of detection.
4. All container images deployed by THE RailOS SHALL be built from verified base images whose checksums are listed in the active SBOM defined in Requirement 38.

---

### Requirement 40: Quantitative Safety Risk Classification

**User Story:** As an Operations_Controller and safety officer, I want advisory outputs to carry a quantified operational risk level derived from probability and impact severity, so that higher-risk advisories receive proportionally more rigorous human review.

#### Acceptance Criteria

1. THE RailOS SHALL compute an operational risk score for each advisory output as the product of the subsystem-reported probability or confidence value and a severity weight assigned to the advisory type (CRITICAL = 4, HIGH = 3, MEDIUM = 2, LOW = 1), producing a risk score in the range [0.0, 4.0].
2. THE RailOS SHALL classify each advisory into a risk tier based on its risk score: Tier 1 (score ≥ 3.2) requires secondary Operations_Controller review before authorization can proceed; Tier 2 (score 2.0–3.19) requires single Operations_Controller authorization; Tier 3 (score < 2.0) may be authorized by any Operations_Controller without additional review.
3. WHEN a Tier 1 advisory is displayed, THE RailOS SHALL require that a second distinct Operations_Controller identity provides an independent authorization action before the advisory is forwarded; the two authorizing identity tokens SHALL be recorded in the audit log.
4. THE RailOS SHALL display the computed risk score and risk tier alongside every advisory in the Operations_Controller interface.

---

### Requirement 41: Geographic Failure Isolation

**User Story:** As an Operations_Controller, I want failures in one corridor segment to be isolated so that they do not propagate to unrelated segments, ensuring that a fault in one geographic area does not degrade advisory services across the entire Corridor.

#### Acceptance Criteria

1. THE RailOS SHALL partition the Corridor into geographic failure isolation zones, with each isolation zone comprising a set of contiguous stations and track segments managed by a dedicated Edge_Node cluster; a failure within one isolation zone SHALL NOT cause subsystem failures or advisory degradation in any other isolation zone.
2. WHEN a failure is detected in one isolation zone — indicated by repeated `SUBSYSTEM_DEGRADED` or `FEED_UNAVAILABLE` alerts from that zone — THE RailOS SHALL enter a zone-isolated degraded mode for that zone only, while all other zones continue at full operational capability.
3. WHEN a zone-isolated degraded mode is active, THE RailOS SHALL display a visual indicator on the Digital_Twin identifying the affected geographic isolation zone and the degradation reason, and SHALL NOT suppress or deprioritize advisories from other zones.

---

### Requirement 42: Dataset Governance

**User Story:** As a Governance_Officer, I want all training and evaluation datasets used for deployed ML models to be versioned with full provenance records, so that the data lineage of any deployed model can be reconstructed and audited.

#### Acceptance Criteria

1. THE RailOS SHALL assign a unique version identifier to every training dataset and evaluation dataset used to train or benchmark a deployed ML model before that dataset is used.
2. THE RailOS SHALL record dataset provenance for each versioned dataset including: source system identifiers (e.g., NTES, OMRS, WILD, synthetic generator), preprocessing steps applied, labeling methodology and annotation tool version where applicable, the UTC timestamp range of the raw data included, and the Engineering_Team member who approved the dataset for use.
3. WHEN a model is approved for deployment, THE RailOS SHALL link the model version identifier to the dataset version identifiers used for its training and evaluation in the traceability matrix defined in Requirement 35.
4. THE RailOS SHALL retain all dataset version records and provenance metadata for a minimum of 365 days.

---

### Requirement 43: Red-Team and Adversarial Testing

**User Story:** As a Security_Officer and Engineering_Team member, I want RailOS to support adversarial simulation exercises and adversarial ML validation, so that the resilience of cybersecurity detection and ML models against deliberate attack is periodically verified.

#### Acceptance Criteria

1. THE RailOS SHALL support periodic red-team simulation exercises for the Cybersecurity_Dashboard by providing a dedicated simulation mode in which synthetic adversarial SCADA traffic patterns (replay attacks, injection patterns, anomalous polling sequences) can be injected into the LSTM autoencoder evaluation pipeline without affecting the live operational data stream.
2. THE Cybersecurity_Dashboard SHALL detect at least 80% of injected adversarial SCADA traffic patterns during red-team exercises, measured as the proportion of injected anomaly events that trigger a `SECURITY_ANOMALY` alert within the 60-second evaluation window.
3. THE RailOS SHALL evaluate all deployed ML models against an adversarial perturbation test dataset — generated using FGSM (Fast Gradient Sign Method) or equivalent — prior to deployment; model performance on the adversarial test set SHALL NOT degrade by more than 15% on the primary metric relative to the clean test set baseline.
4. THE RailOS SHALL record all red-team exercise results and adversarial evaluation results in the model governance audit log with the exercise date, injected pattern count, detection rate, and pass or fail status.

---

### Requirement 44: Edge Node Hardware Telemetry and Thermal Protection

**User Story:** As an Engineering_Team member, I want continuous hardware health monitoring on Edge_Nodes and automatic thermal protection, so that hardware faults are detected early and inference workloads are throttled before hardware damage occurs.

#### Acceptance Criteria

1. THE Edge_Node SHALL continuously monitor and report the following hardware metrics at a sampling interval of no greater than 10 seconds: CPU temperature (°C), GPU utilization (%), memory utilization (%), storage utilization (%), and power supply status (nominal / degraded / failed).
2. THE Edge_Node SHALL expose all hardware health metrics as Prometheus-compatible metrics at the telemetry endpoint defined in Requirement 17.
3. WHEN the Edge_Node CPU or GPU temperature exceeds the manufacturer-specified safe operational threshold, THE Edge_Node SHALL immediately throttle active inference workloads to reduce thermal load, emit a `THERMAL_PROTECTION_ACTIVE` alert to the monitoring topic identifying the component and measured temperature, and log the throttle event with a timestamp.
4. WHEN `THERMAL_PROTECTION_ACTIVE` is active, THE Edge_Node SHALL restore full inference capacity only after the measured temperature falls below the safe operational threshold for a minimum of 60 consecutive seconds, ensuring that thermal oscillation does not cause rapid toggling of inference capacity.

---

### Requirement 45: Digital Twin Visualization Integrity

**User Story:** As an Operations_Controller, I want the Digital Twin to visually distinguish simulated predictions from confirmed real-world operational states, and to display uncertainty indicators on predictive overlays, so that I never mistake a model forecast for a confirmed operational fact.

#### Acceptance Criteria

1. THE Digital_Twin SHALL visually distinguish between confirmed real-world operational states and simulated or predicted states using distinct visual encoding: confirmed states SHALL use solid markers and opaque colours; predicted or simulated states SHALL use dashed borders or hatched fill patterns and SHALL be labelled with the data source type (e.g., "PREDICTED", "SIMULATED") in the map legend.
2. THE Digital_Twin SHALL render uncertainty intervals or confidence indicators for all predictive overlays: delay forecast overlays SHALL display the 90% prediction interval band defined in Requirement 5; failure-probability overlays SHALL display the confidence interval defined in Requirement 4; braking curve advisory overlays SHALL display the "ADVISORY — NOT CERTIFIED" label defined in Requirement 10.
3. WHEN a predictive overlay transitions from predicted state to confirmed state upon receipt of real-world sensor data, THE Digital_Twin SHALL update the visual encoding from predicted to confirmed within 3 seconds of the confirming event being received.
4. THE Digital_Twin SHALL include a persistent legend panel visible at all times that defines the visual encoding conventions distinguishing confirmed, predicted, simulated, stale, and advisory states, ensuring operators can interpret the map without referring to external documentation.
