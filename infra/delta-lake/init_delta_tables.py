"""
RailOS Delta Lake Table Initializer
====================================
Creates all Delta Lake tables on MinIO (S3-compatible) for historical data archival.

Tables:
  - raw_sensor_events       : archived from InfluxDB after 90-day hot retention (Req 1 C4)
  - inference_audit         : ML inference audit records, 365-day retention (Req 11 C5)
  - security_anomaly        : SECURITY_ANOMALY events, 365-day retention (Req 9 C7)
  - model_artifacts_index   : model artifact metadata index
  - maintenance_advisories  : MAINTENANCE_ADVISORY events archive

Partitioning: zone / date / sensor_type (for efficient ML training queries — Task 4.9)

Usage:
    spark-submit init_delta_tables.py
"""

import os
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType,
    BooleanType, LongType, TimestampType, ArrayType, MapType
)

# ── Spark / S3A / Delta configuration ────────────────────────────────────────

MINIO_ENDPOINT  = os.environ.get("MINIO_ENDPOINT",  "http://minio.railos.svc.cluster.local:9000")
MINIO_ACCESS    = os.environ.get("MINIO_ACCESS_KEY", "railos-delta-user")
MINIO_SECRET    = os.environ.get("MINIO_SECRET_KEY", "CHANGE_ME")
DELTA_BUCKET    = os.environ.get("DELTA_BUCKET",     "railos-delta-lake")

BASE_PATH = f"s3a://{DELTA_BUCKET}"

spark = (
    SparkSession.builder
    .appName("railos-delta-init")
    # Delta Lake extension
    .config("spark.sql.extensions",          "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog","org.apache.spark.sql.delta.catalog.DeltaCatalog")
    # S3A connector → MinIO
    .config("spark.hadoop.fs.s3a.endpoint",           MINIO_ENDPOINT)
    .config("spark.hadoop.fs.s3a.access.key",         MINIO_ACCESS)
    .config("spark.hadoop.fs.s3a.secret.key",         MINIO_SECRET)
    .config("spark.hadoop.fs.s3a.path.style.access",  "true")
    .config("spark.hadoop.fs.s3a.impl",               "org.apache.hadoop.fs.s3a.S3AFileSystem")
    .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
    # Performance
    .config("spark.databricks.delta.schema.autoMerge.enabled", "true")
    .config("spark.sql.shuffle.partitions", "8")
    .getOrCreate()
)

spark.sparkContext.setLogLevel("WARN")


# ── Table schemas ─────────────────────────────────────────────────────────────

RAW_SENSOR_SCHEMA = StructType([
    StructField("event_id",        StringType(),    False),   # UUID v4
    StructField("source_id",       StringType(),    False),   # edge-node identifier
    StructField("sensor_type",     StringType(),    False),   # vibration|temperature|gps|...
    StructField("asset_id",        StringType(),    False),   # track-segment or loco id
    StructField("timestamp_utc",   TimestampType(), False),
    StructField("sequence",        LongType(),      True),
    StructField("zone",            StringType(),    False),   # geographic zone (partition key)
    # Payload stored as JSON string to accommodate heterogeneous sensor payloads
    StructField("payload_json",    StringType(),    True),
    StructField("interpolated",    BooleanType(),   True),
    StructField("interpolation_pct", DoubleType(), True),
    StructField("clock_reliable",  BooleanType(),   True),
    StructField("drift_ms",        DoubleType(),    True),
    StructField("schema_version",  StringType(),    True),
    StructField("archived_at",     TimestampType(), True),    # when archived from InfluxDB
])

INFERENCE_AUDIT_SCHEMA = StructType([
    StructField("audit_id",          StringType(),    False),
    StructField("model_id",          StringType(),    False),
    StructField("model_version",     StringType(),    False),  # MAJOR.MINOR.PATCH
    StructField("model_type",        StringType(),    False),  # defect_detector|maintenance|delay|...
    StructField("input_feature_hash", StringType(),   False),  # SHA-256 of input features
    StructField("output_value",      StringType(),    True),   # scalar or structured output JSON
    StructField("timestamp_utc",     TimestampType(), False),
    StructField("edge_node_id",      StringType(),    True),
    StructField("requirement_ids",   StringType(),    True),   # comma-separated req IDs
    StructField("mlflow_run_id",     StringType(),    True),
    StructField("zone",              StringType(),    False),
])

SECURITY_ANOMALY_SCHEMA = StructType([
    StructField("alert_id",           StringType(),    False),
    StructField("iec62443_zone",      StringType(),    False),
    StructField("timestamp_utc",      TimestampType(), False),
    StructField("reconstruction_error", DoubleType(), False),
    StructField("threshold",          DoubleType(),    False),
    StructField("acknowledged",       BooleanType(),   False),
    StructField("acknowledged_by",    StringType(),    True),
    StructField("acknowledged_at",    TimestampType(), True),
    StructField("escalated",          BooleanType(),   True),
    StructField("forensic_artifact_id", StringType(), True),
    StructField("zone",               StringType(),    False),
])

MODEL_ARTIFACTS_SCHEMA = StructType([
    StructField("model_id",       StringType(),    False),
    StructField("model_version",  StringType(),    False),
    StructField("model_type",     StringType(),    False),
    StructField("mlflow_run_id",  StringType(),    False),
    StructField("artifact_path",  StringType(),    False),
    StructField("created_at",     TimestampType(), False),
    StructField("deployed_at",    TimestampType(), True),
    StructField("retired_at",     TimestampType(), True),
    StructField("requirement_ids", StringType(),   True),
    StructField("sbom_version",   StringType(),    True),
    StructField("zone",           StringType(),    False),
])

MAINTENANCE_ADVISORY_SCHEMA = StructType([
    StructField("alert_id",            StringType(),    False),
    StructField("asset_id",            StringType(),    False),
    StructField("failure_probability", DoubleType(),    False),
    StructField("ci_lower",            DoubleType(),    True),
    StructField("ci_upper",            DoubleType(),    True),
    StructField("horizon_hours",       LongType(),      True),
    StructField("data_quality_pct",    DoubleType(),    True),
    StructField("attribution_json",    StringType(),    True),
    StructField("model_version",       StringType(),    True),
    StructField("drift_warning",       BooleanType(),   True),
    StructField("risk_score",          DoubleType(),    True),
    StructField("risk_tier",           LongType(),      True),
    StructField("authorized",          BooleanType(),   True),
    StructField("authorized_by",       StringType(),    True),
    StructField("authorized_at",       TimestampType(), True),
    StructField("timestamp_utc",       TimestampType(), False),
    StructField("zone",                StringType(),    False),
])


# ── Helper: create empty Delta table ─────────────────────────────────────────

def create_delta_table(name: str, schema: StructType, partition_cols: list, path: str):
    """Create an empty Delta Lake table at path if it doesn't already exist."""
    full_path = f"{BASE_PATH}/{path}"
    print(f"  Creating Delta table '{name}' at {full_path}")
    try:
        empty_df = spark.createDataFrame([], schema)
        (
            empty_df.write
            .format("delta")
            .mode("ignore")           # no-op if table already exists
            .partitionBy(*partition_cols)
            .option("delta.logRetentionDuration", "interval 365 days")
            .option("delta.deletedFileRetentionDuration", "interval 30 days")
            .save(full_path)
        )
        # Register in Spark catalog for SQL access
        spark.sql(f"""
            CREATE TABLE IF NOT EXISTS {name}
            USING DELTA
            LOCATION '{full_path}'
        """)
        print(f"  ✓ {name}")
    except Exception as exc:
        print(f"  ✗ {name}: {exc}")
        raise


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("RailOS Delta Lake — Table Initialization")
    print(f"  MinIO endpoint : {MINIO_ENDPOINT}")
    print(f"  Delta bucket   : {DELTA_BUCKET}")
    print("=" * 60)

    # database / namespace
    spark.sql("CREATE DATABASE IF NOT EXISTS railos_archive")
    spark.catalog.setCurrentDatabase("railos_archive")

    tables = [
        # (catalog_name, schema, partition_cols, s3_path_suffix)
        (
            "raw_sensor_events",
            RAW_SENSOR_SCHEMA,
            ["zone", "sensor_type"],          # efficient ML training queries (Task 4.9)
            "raw_sensor_events",
        ),
        (
            "inference_audit",
            INFERENCE_AUDIT_SCHEMA,
            ["model_type", "zone"],
            "inference_audit",
        ),
        (
            "security_anomaly",
            SECURITY_ANOMALY_SCHEMA,
            ["iec62443_zone"],
            "security_anomaly",
        ),
        (
            "model_artifacts_index",
            MODEL_ARTIFACTS_SCHEMA,
            ["model_type"],
            "model_artifacts_index",
        ),
        (
            "maintenance_advisories",
            MAINTENANCE_ADVISORY_SCHEMA,
            ["zone"],
            "maintenance_advisories",
        ),
    ]

    for name, schema, partitions, path in tables:
        create_delta_table(name, schema, partitions, path)

    print("\nTable summary:")
    spark.sql("SHOW TABLES IN railos_archive").show(truncate=False)
    print("\nDelta Lake initialization complete.")


if __name__ == "__main__":
    main()
