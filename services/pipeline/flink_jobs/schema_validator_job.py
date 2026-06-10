"""
RailOS Schema Validation Flink Job
====================================
PyFlink DataStream job that:

1. Consumes raw events from all ``track.sensor.*`` and ``train.telemetry.*``
   Kafka source topics.
2. Validates each event against the canonical sensor-event JSON schema.
3. Valid events → published to the original destination topic unchanged.
4. Invalid events → published to ``dead-letter.schema-failures`` with error
   details + a ``SCHEMA_VALIDATION_FAILURE`` alert emitted to
   ``monitoring.alerts``.

Exactly-once semantics are achieved via Flink checkpointing with the Kafka
exactly-once producer sink (``EXACTLY_ONCE`` semantic).

Design §4.2–4.3 / Req 1.7
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import jsonschema
from pyflink.common import WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.checkpointing_mode import CheckpointingMode
from pyflink.datastream.connectors.kafka import (
    FlinkKafkaConsumer,
    FlinkKafkaProducer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.functions import MapFunction, OutputTag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment / Config (supplied via 01-configmap.yaml)
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS: str = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka.railos-kafka.svc:9092"
)
SCHEMA_REGISTRY_URL: str = os.environ.get(
    "SCHEMA_REGISTRY_URL", "http://apicurio-registry.railos-pipeline.svc:8080"
)
FLINK_PARALLELISM: int = int(os.environ.get("FLINK_PARALLELISM", "4"))

# Kafka topic patterns consumed by this job
SOURCE_TOPICS: list[str] = [
    "track.sensor.vibration",
    "track.sensor.temperature",
    "track.sensor.acoustic",
    "train.telemetry.position",
    "train.telemetry.omrs",
    "train.telemetry.wild",
]

DEAD_LETTER_TOPIC = "dead-letter.schema-failures"
MONITORING_TOPIC = "monitoring.alerts"

# ---------------------------------------------------------------------------
# Inline schema — loaded at job-manager startup so task managers inherit it.
# In production the schema bytes are fetched once from the registry and
# broadcast; here we embed the schema for robustness / offline operation.
# ---------------------------------------------------------------------------
_CANONICAL_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "eventId", "sourceId", "sensorType", "assetId",
        "timestamp_utc", "sequence", "payload", "quality_flags", "schema_version",
    ],
    "properties": {
        "eventId": {"type": "string"},
        "sourceId": {"type": "string", "minLength": 1},
        "sensorType": {
            "type": "string",
            "enum": ["vibration", "temperature", "gps", "wheel_load", "acoustic", "camera"],
        },
        "assetId": {"type": "string", "minLength": 1},
        "timestamp_utc": {"type": "string"},
        "sequence": {"type": "integer", "minimum": 0},
        "payload": {"type": "object"},
        "quality_flags": {
            "type": "object",
            "required": ["interpolated", "interpolation_pct", "clock_reliable", "drift_ms"],
            "properties": {
                "interpolated": {"type": "boolean"},
                "interpolation_pct": {"type": "number", "minimum": 0.0, "maximum": 100.0},
                "clock_reliable": {"type": "boolean"},
                "drift_ms": {"type": "number"},
            },
        },
        "schema_version": {"type": "string"},
    },
}

_VALIDATOR = jsonschema.Draft7Validator(_CANONICAL_SCHEMA)

# Side-output tag for invalid events
INVALID_TAG = OutputTag("invalid_events", Types.STRING())


# ---------------------------------------------------------------------------
# Map function
# ---------------------------------------------------------------------------
class SchemaValidatorFunction(MapFunction):
    """
    Validates a raw JSON event string against the canonical schema.

    Output: tuple(is_valid: bool, original_json: str, error_json: str | None)
    """

    def map(self, value: str) -> tuple[bool, str, str | None]:  # type: ignore[override]
        try:
            event: dict[str, Any] = json.loads(value)
        except json.JSONDecodeError as exc:
            error_payload = self._build_error_payload(
                raw=value, errors=[], parse_error=str(exc)
            )
            return (False, value, json.dumps(error_payload))

        errors = sorted(_VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
        if errors:
            error_payload = self._build_error_payload(raw=value, errors=errors)
            return (False, value, json.dumps(error_payload))

        return (True, value, None)

    @staticmethod
    def _build_error_payload(
        raw: str,
        errors: list[jsonschema.ValidationError],
        parse_error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "alert_type": "SCHEMA_VALIDATION_FAILURE",
            "timestamp_ms": int(time.time() * 1000),
            "raw_event": raw,
            "validation_errors": [
                {"path": list(e.absolute_path), "message": e.message}
                for e in errors
            ],
            "parse_error": parse_error,
        }


def _make_alert(source_feed: str, raw_event: str, errors: list[dict]) -> str:
    """Build a SCHEMA_VALIDATION_FAILURE alert for monitoring.alerts."""
    return json.dumps({
        "alert_type": "SCHEMA_VALIDATION_FAILURE",
        "source_feed": source_feed,
        "timestamp_ms": int(time.time() * 1000),
        "raw_event_snippet": raw_event[:256],
        "error_count": len(errors),
    })


# ---------------------------------------------------------------------------
# Kafka helpers
# ---------------------------------------------------------------------------
def _kafka_source(topics: list[str]) -> KafkaSource:
    return (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP_SERVERS)
        .set_topics(*topics)
        .set_group_id("railos-schema-validator")
        .set_value_only_deserializer(SimpleStringSchema())
        .set_starting_offsets(
            # Resume from committed offsets in production; earliest for bootstrap
            # KafkaOffsetsInitializer.committed_offsets(OffsetResetStrategy.EARLIEST)
        )
        .build()
    )


def _kafka_sink(topic: str) -> KafkaSink:
    return (
        KafkaSink.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP_SERVERS)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(topic)
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .set_deliver_guarantee("EXACTLY_ONCE")
        .build()
    )


# ---------------------------------------------------------------------------
# Main job graph
# ---------------------------------------------------------------------------
def build_and_run() -> None:
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(FLINK_PARALLELISM)

    # Enable exactly-once checkpointing
    env.enable_checkpointing(30_000, CheckpointingMode.EXACTLY_ONCE)
    env.get_checkpoint_config().set_min_pause_between_checkpoints(5_000)
    env.get_checkpoint_config().set_checkpoint_timeout(60_000)

    # ---------------------------------------------------------------------------
    # Source: all sensor topics
    # ---------------------------------------------------------------------------
    source = _kafka_source(SOURCE_TOPICS)
    raw_stream = env.from_source(
        source,
        WatermarkStrategy.no_watermarks(),
        "sensor-kafka-source",
    )

    # ---------------------------------------------------------------------------
    # Validate
    # ---------------------------------------------------------------------------
    validated = raw_stream.map(SchemaValidatorFunction(), output_type=Types.TUPLE([
        Types.BOOLEAN(), Types.STRING(), Types.STRING(),
    ]))

    valid_stream = validated.filter(lambda t: t[0]).map(lambda t: t[1])
    invalid_stream = validated.filter(lambda t: not t[0]).map(lambda t: t[2])

    # ---------------------------------------------------------------------------
    # Dead-letter sink
    # ---------------------------------------------------------------------------
    invalid_stream.sink_to(_kafka_sink(DEAD_LETTER_TOPIC)).name("dead-letter-sink")

    # ---------------------------------------------------------------------------
    # Monitoring alert from invalid events
    # ---------------------------------------------------------------------------
    alert_stream = (
        validated.filter(lambda t: not t[0])
        .map(lambda t: json.dumps({
            "alert_type": "SCHEMA_VALIDATION_FAILURE",
            "timestamp_ms": int(time.time() * 1000),
            "raw_event_snippet": (t[1] or "")[:256],
        }))
    )
    alert_stream.sink_to(_kafka_sink(MONITORING_TOPIC)).name("monitoring-alert-sink")

    # ---------------------------------------------------------------------------
    # Pass-through valid events back to their original topics.
    # For the schema-validator job the destination topic mirrors the source;
    # downstream consumers read from the same topics.  In environments where
    # a separate "validated.*" namespace is preferred, swap the topic mapping.
    # ---------------------------------------------------------------------------
    valid_stream.sink_to(
        KafkaSink.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP_SERVERS)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            # Topic routing based on the sensorType field would go here;
            # for simplicity the validator publishes to a validated namespace.
            .set_topic_selector(lambda record, _: _route_valid(record))
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .set_deliver_guarantee("EXACTLY_ONCE")
        .build()
    ).name("valid-events-sink")

    env.execute("railos-schema-validator")


def _route_valid(record: str) -> str:
    """
    Route a valid event back to its destination topic.

    The schema validator publishes valid events unchanged; downstream Flink
    jobs consume from the same topic.  This function is a no-op passthrough
    mapping — it returns the same topic the event arrived on by inspecting
    the sensorType field.
    """
    try:
        evt = json.loads(record)
        sensor_type = evt.get("sensorType", "")
        topic_map = {
            "vibration": "track.sensor.vibration",
            "temperature": "track.sensor.temperature",
            "acoustic": "track.sensor.acoustic",
            "gps": "train.telemetry.position",
            "wheel_load": "train.telemetry.wild",
        }
        return topic_map.get(sensor_type, "train.telemetry.omrs")
    except (json.JSONDecodeError, AttributeError):
        return "dead-letter.schema-failures"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_and_run()
