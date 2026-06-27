-- RailOS-X PostgreSQL Initialization for Local Development
-- Creates all tables needed by the services

-- Authorization Gate audit log (Req 12, Req 30)
CREATE TABLE IF NOT EXISTS authorization_audit (
    audit_id          UUID PRIMARY KEY,
    advisory_id       TEXT NOT NULL,
    action            TEXT NOT NULL CHECK (action IN ('AUTHORIZE', 'REJECT')),
    controller_identity TEXT NOT NULL,
    timestamp_utc     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    risk_tier         INTEGER NOT NULL CHECK (risk_tier IN (1, 2, 3)),
    risk_score        NUMERIC(4,2) NOT NULL CHECK (risk_score >= 0 AND risk_score <= 4.0),
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_advisory ON authorization_audit(advisory_id);
CREATE INDEX IF NOT EXISTS idx_auth_audit_timestamp ON authorization_audit(timestamp_utc);

-- Hazard Register (Req 35, append-only)
CREATE TABLE IF NOT EXISTS hazard_register (
    hazard_id         UUID PRIMARY KEY,
    hazard_code       TEXT NOT NULL,
    severity          TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    description       TEXT NOT NULL,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_alert_id   UUID,
    status            TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'REVIEW_REQUIRED', 'MITIGATED', 'ACCEPTED')),
    mitigations       JSONB DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hazard_status ON hazard_register(status);

-- Traceability matrix (Req 35 C3)
CREATE TABLE IF NOT EXISTS traceability_matrix (
    entry_id          UUID PRIMARY KEY,
    requirement_id    TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    evidence_type     TEXT NOT NULL,
    evidence_ref      TEXT NOT NULL,
    hazard_refs       TEXT[] DEFAULT '{}',
    verified_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_by       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trace_requirement ON traceability_matrix(requirement_id);
CREATE INDEX IF NOT EXISTS idx_trace_model ON traceability_matrix(model_version);

-- Model registry metadata (MLflow complement for governance)
CREATE TABLE IF NOT EXISTS model_deployments (
    deployment_id     UUID PRIMARY KEY,
    model_name        TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    deployed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deployed_by       TEXT NOT NULL,
    benchmark_passed  BOOLEAN NOT NULL DEFAULT false,
    fairness_passed   BOOLEAN NOT NULL DEFAULT false,
    adversarial_passed BOOLEAN NOT NULL DEFAULT false,
    rollback_of       UUID REFERENCES model_deployments(deployment_id)
);

-- Digital Twin state persistence
CREATE TABLE IF NOT EXISTS digital_twin_state (
    entity_id         TEXT PRIMARY KEY,
    entity_type       TEXT NOT NULL,
    state_json        JSONB NOT NULL,
    last_updated      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Edge node registry
CREATE TABLE IF NOT EXISTS edge_nodes (
    node_id           TEXT PRIMARY KEY,
    station_name      TEXT NOT NULL,
    latitude          NUMERIC(9,6),
    longitude         NUMERIC(9,6),
    last_heartbeat    TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'UNKNOWN',
    model_versions    JSONB DEFAULT '{}'::jsonb
);

GRANT ALL ON ALL TABLES IN SCHEMA public TO railos;
