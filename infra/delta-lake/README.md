# RailOS Delta Lake Storage Layer

Delta Lake on MinIO (S3-compatible) provides long-term historical storage for sensor events
archived from InfluxDB after their 90-day hot retention expires (Req 1 C4), plus immutable
audit and governance tables retained for 365 days (Req 9 C7, Req 11 C5).

## Tables

| Table | Partition Keys | Retention | Purpose |
|-------|---------------|-----------|---------|
| `raw_sensor_events` | zone, sensor_type | 90d → archive | InfluxDB overflow archive for ML retraining |
| `inference_audit` | model_type, zone | 365d | ML inference audit records (Req 11) |
| `security_anomaly` | iec62443_zone | 365d | SECURITY_ANOMALY event archive (Req 9 C7) |
| `model_artifacts_index` | model_type | indefinite | Model version metadata index |
| `maintenance_advisories` | zone | 365d | MAINTENANCE_ADVISORY event archive |

Partitioning by `zone` and `sensor_type` enables efficient ML training queries (Task 4.9).

## Prerequisites

1. MinIO deployed and `railos-delta-lake` bucket created (Task 1.10 — `infra/minio/`)
2. Kubernetes `railos` namespace exists (Task 1.1 — `infra/kafka/namespace.yaml`)

## Deployment

### 1. Build the init image

```bash
docker build -t railos/delta-init:1.0.0 infra/delta-lake/
# Push to your registry
docker push your-registry/railos/delta-init:1.0.0
```

Update the `image:` field in `03-init-job.yaml` to your registry path.

### 2. Apply manifests

```bash
kubectl apply -f infra/delta-lake/01-configmap.yaml -n railos
kubectl apply -f infra/delta-lake/02-secrets.yaml   -n railos   # update secret values first
kubectl apply -f infra/delta-lake/03-init-job.yaml  -n railos
```

### 3. Verify

```bash
# Watch the init job
kubectl logs -f job/delta-lake-init -n railos

# Confirm tables exist via Spark shell (optional)
kubectl run spark-shell --rm -it \
  --image=railos/delta-init:1.0.0 \
  --restart=Never -n railos \
  -- python -c "
from pyspark.sql import SparkSession
spark = SparkSession.builder.appName('check').getOrCreate()
spark.sql('SHOW TABLES IN railos_archive').show()
"
```

## Schema evolution

Delta Lake auto-merges compatible schema changes (`autoMerge.enabled=true`).
For breaking changes, create a new table version and update the archival pipeline.

## Integration with Task 4.9 (Compaction)

The compaction CronJob defined in Task 4.9 (`infra/flink/` or a separate Spark CronJob)
will:
- `OPTIMIZE` each Delta table to compact small Parquet files
- `VACUUM` with 7-day retention on deleted files
- Re-partition large tables by `date` in addition to zone/sensor_type
