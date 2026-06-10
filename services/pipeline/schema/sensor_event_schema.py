"""
RailOS Canonical Sensor Event JSON Schema (Task 4.2)
Satisfies: Req 1 C5 (canonical schema), Design §4.3
"""

SENSOR_EVENT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "railos.sensor.event",
    "title": "CanonicalSensorEvent",
    "type": "object",
    "required": [
        "eventId", "sourceId", "sensorType", "assetId",
        "timestamp_utc", "sequence", "payload", "quality_flags", "schema_version"
    ],
    "additionalProperties": False,
    "properties": {
        "eventId":       {"type": "string"},
        "sourceId":      {"type": "string", "minLength": 1},
        "sensorType":    {
            "type": "string",
            "enum": ["vibration", "temperature", "gps", "wheel_load", "acoustic", "camera"]
        },
        "assetId":       {"type": "string", "minLength": 1},
        "timestamp_utc": {"type": "string"},
        "sequence":      {"type": "integer", "minimum": 0},
        "payload":       {"type": "object", "minProperties": 1},
        "quality_flags": {
            "type": "object",
            "required": ["interpolated", "interpolation_pct", "clock_reliable", "drift_ms"],
            "properties": {
                "interpolated":      {"type": "boolean"},
                "interpolation_pct": {"type": "number", "minimum": 0, "maximum": 100},
                "clock_reliable":    {"type": "boolean"},
                "drift_ms":          {"type": "number"},
            },
            "additionalProperties": False,
        },
        "schema_version": {"type": "string"},
    },
}
