"""
RailOS Canonical Sensor Event Model
=====================================
Pydantic model for the canonical sensor event schema (Design §4.3).
All legacy adapter outputs must be normalised to this schema before
publishing to Kafka.

Schema version: 1.0.0
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class QualityFlags(BaseModel):
    """Quality metadata attached to every canonical event."""

    interpolated: bool = False
    interpolation_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    clock_reliable: bool = True
    drift_ms: float = 0.0


class CanonicalEvent(BaseModel):
    """
    Canonical sensor event schema (Design §4.3).

    All adapters produce events conforming to this model.  ``to_kafka_message()``
    serialises the event to UTF-8 JSON bytes suitable for a Kafka producer.
    """

    eventId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sourceId: str
    sensorType: str  # vibration | temperature | gps | wheel_load | acoustic | camera
    assetId: str
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sequence: int
    payload: dict[str, Any]
    quality_flags: QualityFlags = Field(default_factory=QualityFlags)
    schema_version: str = "1.0.0"

    @field_validator("sensorType")
    @classmethod
    def validate_sensor_type(cls, v: str) -> str:
        allowed = {"vibration", "temperature", "gps", "wheel_load", "acoustic", "camera"}
        if v not in allowed:
            raise ValueError(f"sensorType must be one of {allowed}, got {v!r}")
        return v

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, v: int) -> int:
        if v < 0:
            raise ValueError("sequence must be a non-negative integer")
        return v

    def to_kafka_message(self) -> bytes:
        """Serialise to UTF-8 JSON bytes for a Kafka producer value."""
        return self.model_dump_json().encode("utf-8")
