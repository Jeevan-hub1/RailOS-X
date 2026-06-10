# RailOS Scripts

Operational scripts organized by domain. All scripts are idempotent and safe to re-run.

---

## Directory Structure

```
scripts/
├── dr/                     # Disaster Recovery (Tasks 20.1–20.7)
│   ├── verify_kafka_ha.sh              # Verify Kafka RF=3, test failover
│   ├── verify_influxdb_replication.sh  # Verify InfluxDB WAL replication ≤60s
│   ├── verify_patroni_failover.sh      # Test PostgreSQL Patroni failover RTO
│   ├── backup-cronjob.yaml             # Daily backup CronJob (02:00 UTC)
│   ├── backup-integrity-test.yaml      # Daily restore integrity test (04:00 UTC)
│   ├── test_edge_autonomous.sh         # Simulate central outage, test edge autonomy
│   └── README.md
│
├── pipeline/               # Data Pipeline (Task 4.1, 4.8)
│   ├── create_kafka_topics.sh          # Create all 17 RailOS Kafka topics
│   └── throughput_test.sh              # Verify 10,000 events/sec throughput
│
├── security/               # Security (Tasks 16.1–16.5, 17.1)
│   ├── verify_psa.sh                   # Verify Pod Security Admission (restricted)
│   └── verify_supply_chain.sh          # Verify cosign signatures, SBOM, Grype
│
├── safety/                 # Safety & Compliance (Tasks 21.2, 21.5)
│   ├── verify_en50128.sh               # Audit EN 50128 alignment (deterministic inference)
│   └── generate_traceability_report.sh # Generate traceability JSON for a model version
│
├── mlops/                  # Model Governance (Tasks 18.2, 18.7)
│   ├── run_benchmark_gate.sh           # Run pytest benchmark suite before deployment
│   └── rollback_model.sh               # Rollback a deployed model (RTO ≤ 15 min)
│
└── validation/             # Simulation & Integration Validation (Tasks 24, 25.4)
    ├── run_simulation_validation.sh    # Digital Twin accuracy + MARL success rate
    └── run_geographic_isolation_test.sh # Zone-A failure must not affect Zone-B
```

---

## Prerequisites

```bash
# Make all scripts executable
find scripts/ -name "*.sh" -exec chmod +x {} \;
```

Most scripts require:
- `kubectl` configured for the `railos` cluster
- `NAMESPACE=railos` environment variable (default)
- For API scripts: `RAILOS_TOKEN` = valid Engineering_Team or Security_Officer JWT

---

## Quick Reference

| Task | Script | Requirement |
|------|--------|-------------|
| Verify Kafka HA | `dr/verify_kafka_ha.sh` | Req 15, 16 |
| Verify InfluxDB RPO ≤60s | `dr/verify_influxdb_replication.sh` | Req 16 C2 |
| Test Patroni failover | `dr/verify_patroni_failover.sh` | Req 16 C2 |
| Create Kafka topics | `pipeline/create_kafka_topics.sh` | Req 1 |
| Throughput test 10k/s | `pipeline/throughput_test.sh` | Req 1 C6 |
| Verify PSA restricted | `security/verify_psa.sh` | Req 39 |
| Supply chain check | `security/verify_supply_chain.sh` | Req 38 |
| EN 50128 audit | `safety/verify_en50128.sh` | Design §13 |
| Traceability report | `safety/generate_traceability_report.sh` | Req 35 C3 |
| Benchmark gate | `mlops/run_benchmark_gate.sh` | Req 14 |
| Model rollback | `mlops/rollback_model.sh` | Req 11 C3 |
| Simulation validation | `validation/run_simulation_validation.sh` | Req 32 |
| Geographic isolation | `validation/run_geographic_isolation_test.sh` | Req 41 |
