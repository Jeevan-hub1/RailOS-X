# PostGIS — Digital Twin Geospatial Layer

Dedicated PostgreSQL 15 + PostGIS 3.4 instance for the RailOS Digital Twin
geospatial layer (Design §7.1 Layers A and B). This is **separate** from the
Patroni HA cluster in `infra/postgresql/` (Task 1.3).

---

## Purpose

| Layer | Role |
|-------|------|
| Layer A — Asset Data Model | `asset_registry` table: stores IR GIS track geometry (LineString, EPSG:4326), station/bridge/tunnel assets with spatial columns, spec_version, maintenance linkage |
| Layer B — Geospatial Layer | PostGIS spatial queries: nearest asset to GPS coordinate, segment geometry intersection, corridor bounding-box lookups |

The Digital Twin's `SELECT assetId, type, location_geojson, spec_version, maintenance_history`
query pattern (Design §7.1) is served from this instance.

Actual GIS data import (IR corridor geometry) is handled by **Task 13.1**; this
task only provisions the PostGIS instance and schema.

---

## Files

| File | Description |
|------|-------------|
| `01-secrets.yaml` | PostGIS superuser + `railos_spatial` user credentials (placeholders) |
| `02-configmap.yaml` | `postgresql.conf` tuned for spatial workloads + `init.sh` schema bootstrap |
| `03-services.yaml` | ClusterIP service (port 5432) + headless service |
| `04-statefulset.yaml` | PostGIS 15-3.4 StatefulSet (1 replica, 50 Gi PVC, non-root, probes, exporter sidecar) |
| `05-prometheus-rules.yaml` | PrometheusRule alerts: `pg_up`, connection count, PVC usage, exporter health |

---

## Prerequisites

1. The `railos` namespace must exist (created by `infra/postgresql/00-namespace.yaml`).
2. Prometheus Operator (`kube-prometheus-stack`) must be installed for `PrometheusRule` CRD support.
3. A `standard` storage class (or equivalent SSD-backed class) must be available in your cluster.

---

## Deployment

### 1. Replace placeholder secrets

Edit `01-secrets.yaml` and replace all `REPLACE_WITH_*` values with strong randomly generated passwords:

```bash
# Generate passwords
openssl rand -base64 32   # superuser-password
openssl rand -base64 32   # spatial-user-password
```

Update `data-source-name` in the `postgis-exporter-secret` to match `spatial-user-password`.

> **Production**: Use HashiCorp Vault with the External Secrets Operator or Vault Agent Injector
> to inject credentials at runtime instead of storing them in this file (Req 37).

### 2. Apply manifests in order

```bash
# From the repo root
kubectl apply -f infra/postgis/01-secrets.yaml
kubectl apply -f infra/postgis/02-configmap.yaml
kubectl apply -f infra/postgis/03-services.yaml
kubectl apply -f infra/postgis/04-statefulset.yaml
kubectl apply -f infra/postgis/05-prometheus-rules.yaml
```

Or apply the entire directory at once:

```bash
kubectl apply -f infra/postgis/
```

### 3. Verify the pod is running

```bash
kubectl get pods -n railos -l app=postgis
# Expected: postgis-0   2/2   Running   0   <age>
# (2 containers: postgis + postgres-exporter)

kubectl get pvc -n railos -l app=postgis
# Expected: postgis-data-postgis-0   Bound   50Gi
```

### 4. Verify PostGIS and schema

```bash
# Connect to the spatial database
kubectl exec -it -n railos postgis-0 -c postgis -- \
  psql -U postgres -d railos_spatial

# Inside psql — verify PostGIS version
SELECT PostGIS_Full_Version();

# Verify tables and spatial indexes
\dt
\di idx_asset_registry_location_gist
\di idx_asset_registry_geometry_gist
\di idx_track_segments_line_geometry_gist

# Test a spatial query (empty result expected before Task 13.1 GIS import)
SELECT asset_id, asset_type, name,
       ST_AsGeoJSON(location) AS location_geojson
FROM   asset_registry
LIMIT  5;
```

### 5. Check Prometheus alerts

```bash
kubectl get prometheusrule -n railos postgis-alerts
# Verify the rule is picked up by Prometheus
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
# Open http://localhost:9090/rules and search for 'postgis'
```

---

## Schema Overview

### `asset_registry`

Stores physical assets (track segments, bridges, tunnels, stations, sensors, etc.)
with two spatial columns:

| Column | Type | Description |
|--------|------|-------------|
| `asset_id` | UUID PK | Unique asset identifier |
| `asset_type` | TEXT | `track_segment`, `bridge`, `tunnel`, `station`, … |
| `name` | TEXT | Human-readable asset name |
| `location` | `GEOMETRY(POINT, 4326)` | Point GPS location (WGS84) |
| `geometry` | `GEOMETRY(LINESTRING, 4326)` | Linear extent (track run, bridge span) |
| `spec_version` | TEXT | IFC 4.x BIM version reference |
| `zone` | TEXT | IEC 62443 / geographic zone identifier |
| `metadata` | JSONB | Extensible properties |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | Auto-updated on modification |

GIST indexes: `idx_asset_registry_location_gist`, `idx_asset_registry_geometry_gist`

### `track_segments`

Directed track topology graph — one row per corridor segment:

| Column | Type | Description |
|--------|------|-------------|
| `segment_id` | UUID PK | Unique segment identifier |
| `line_geometry` | `GEOMETRY(LINESTRING, 4326)` | Segment path (WGS84) — **NOT NULL** |
| `zone` | TEXT | Geographic zone |
| `speed_limit_kmh` | INT | Maximum permitted speed |
| `max_concurrent_trains` | INT | Capacity limit (used by state conflict detector, Design §7.3) |
| `metadata` | JSONB | Gradient, track class, electrification, etc. |

GIST index: `idx_track_segments_line_geometry_gist`

---

## Spatial Query Examples

```sql
-- Nearest asset to a GPS coordinate (KNN search)
SELECT asset_id, name, asset_type,
       ST_Distance(location::geography,
                   ST_SetSRID(ST_MakePoint(78.4867, 17.3850), 4326)::geography) AS dist_m
FROM   asset_registry
WHERE  location IS NOT NULL
ORDER  BY location <-> ST_SetSRID(ST_MakePoint(78.4867, 17.3850), 4326)
LIMIT  5;

-- Track segments intersecting a bounding box (corridor tile query)
SELECT segment_id, zone, speed_limit_kmh
FROM   track_segments
WHERE  ST_Intersects(
         line_geometry,
         ST_MakeEnvelope(78.0, 17.0, 79.0, 18.0, 4326)
       );

-- Assets within 500m of a defect alert GPS coordinate
SELECT asset_id, asset_type, name
FROM   asset_registry
WHERE  ST_DWithin(
         location::geography,
         ST_SetSRID(ST_MakePoint(78.52, 17.41), 4326)::geography,
         500   -- metres
       );
```

---

## Configuration

### Storage class

The StatefulSet uses `storageClassName: standard`. For production, replace with
your cluster's SSD-backed storage class:

| Platform | Recommended class |
|----------|------------------|
| AWS EKS | `gp3` |
| GKE | `premium-rwo` |
| AKS | `managed-premium` |
| On-prem (Rook-Ceph) | `rook-ceph-block` |
| On-prem (Longhorn) | `longhorn` |

### Resource tuning

`postgresql.conf` defaults (set in `02-configmap.yaml`):

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `shared_buffers` | 512 MB | Cache hot GIST index pages |
| `work_mem` | 64 MB | Reduce spill-to-disk on spatial sort/join operations |
| `maintenance_work_mem` | 256 MB | Faster GIST index builds during Task 13.1 GIS import |
| `max_connections` | 50 | Digital Twin uses a small connection pool |

For large GIS imports (Task 13.1), temporarily increase `maintenance_work_mem` to 1 GB
to speed up index creation:

```bash
kubectl exec -it -n railos postgis-0 -c postgis -- \
  psql -U postgres -d railos_spatial -c \
  "ALTER SYSTEM SET maintenance_work_mem = '1GB'; SELECT pg_reload_conf();"
# Reset after import
kubectl exec -it -n railos postgis-0 -c postgis -- \
  psql -U postgres -d railos_spatial -c \
  "ALTER SYSTEM RESET maintenance_work_mem; SELECT pg_reload_conf();"
```

---

## Upgrading PostGIS

1. Update the image tag in `04-statefulset.yaml` (e.g. `15-3.4` → `15-3.5`).
2. Apply: `kubectl apply -f infra/postgis/04-statefulset.yaml`
3. The StatefulSet `RollingUpdate` strategy will restart the pod.
4. Verify after upgrade: `SELECT PostGIS_Full_Version();`

For a major PostgreSQL version upgrade (e.g. 15 → 16), a `pg_upgrade` or logical
replication migration is required. Consult the PostGIS upgrade documentation.

---

## Monitoring

Prometheus alerts defined in `05-prometheus-rules.yaml`:

| Alert | Threshold | Severity |
|-------|-----------|----------|
| `PostGISDown` | `pg_up == 0` for 1 min | critical |
| `PostGISUnreachableWarning` | `pg_up == 0` for 30s | warning |
| `PostGISConnectionsHigh` | connections > 40 (80%) for 5 min | warning |
| `PostGISConnectionsNearLimit` | connections ≥ 48 (96%) for 2 min | critical |
| `PostGISPVCUsageHigh` | PVC > 70% for 5 min | warning |
| `PostGISPVCUsageCritical` | PVC > 90% for 2 min | critical |
| `PostGISExporterDown` | exporter scrape fails for 3 min | warning |

---

## Relationship to Other Components

| Component | Relationship |
|-----------|-------------|
| `infra/postgresql/` (Patroni) | **Separate** instance — audit logs, hazard register, traceability. Do not confuse. |
| Digital Twin (Task 3.x) | Primary consumer — queries `asset_registry` and `track_segments` for GIS rendering |
| Task 13.1 — GIS Data Import | Imports actual IR corridor geometry into `track_segments` and `asset_registry` |
| Prometheus / Grafana | Scrapes postgres_exporter sidecar on port 9187 |
