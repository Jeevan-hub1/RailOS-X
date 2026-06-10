"""
RailOS Schema Registry Client (Task 4.2)
Registers the canonical sensor event schema with Apicurio and validates events.
Satisfies: Req 1 C2 (normalize to canonical schema), Req 1 C7 (schema validation failures)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
import jsonschema
from jsonschema import ValidationError

from .sensor_event_schema import SENSOR_EVENT_SCHEMA

log = logging.getLogger(__name__)

SCHEMA_REGISTRY_URL = os.environ.get(
    "SCHEMA_REGISTRY_URL", "http://apicurio.railos.svc.cluster.local:8080"
)
SCHEMA_NAME = os.environ.get("SCHEMA_NAME", "railos.sensor.event")
SCHEMA_VERSION = os.environ.get("SCHEMA_VERSION", "1")

_validator = jsonschema.Draft7Validator(SENSOR_EVENT_SCHEMA)


class SchemaValidationError(ValueError):
    """Raised when an event fails canonical schema validation."""

    def __init__(self, message: str, field_errors: list[str]) -> None:
        super().__init__(message)
        self.field_errors = field_errors


def register_schema() -> bool:
    """Register the canonical sensor event schema with Apicurio on startup.

    Returns True on success, False if registry is unavailable (non-fatal for pilot).
    """
    url = f"{SCHEMA_REGISTRY_URL}/apis/registry/v2/groups/railos/artifacts"
    payload = {
        "id": SCHEMA_NAME,
        "type": "JSON",
        "version": SCHEMA_VERSION,
        "content": json.dumps(SENSOR_EVENT_SCHEMA),
    }
    try:
        resp = httpx.post(url, json=payload, timeout=5.0)
        if resp.status_code in (200, 201, 409):  # 409 = already exists
            log.info("Schema registered/confirmed: %s v%s", SCHEMA_NAME, SCHEMA_VERSION)
            return True
        log.warning("Schema registration returned HTTP %d", resp.status_code)
        return False
    except Exception as exc:
        log.warning("Schema registry unavailable (non-fatal): %s", exc)
        return False


def validate(event_dict: dict[str, Any]) -> None:
    """Validate an event dict against the canonical sensor event schema.

    Raises SchemaValidationError with field-level details on failure.
    Completes without exception if event is valid.
    """
    errors = sorted(_validator.iter_errors(event_dict), key=lambda e: list(e.path))
    if errors:
        field_errors = [
            f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in errors
        ]
        raise SchemaValidationError(
            f"Event failed schema validation ({len(errors)} error(s))",
            field_errors,
        )
