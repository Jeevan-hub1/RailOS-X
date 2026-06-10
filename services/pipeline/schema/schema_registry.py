"""
RailOS Schema Registry Client
==============================
Registers the canonical sensor-event JSON schema with Apicurio Schema Registry
and validates incoming events before they enter the Kafka processing pipeline.

Design §4.2 / Req 1.7
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (injected via ConfigMap – see 01-configmap.yaml)
# ---------------------------------------------------------------------------
SCHEMA_REGISTRY_URL: str = os.environ.get(
    "SCHEMA_REGISTRY_URL", "http://apicurio-registry.railos-pipeline.svc:8080"
)
SCHEMA_NAME: str = os.environ.get("SCHEMA_NAME", "railos.sensor.event")
SCHEMA_VERSION: str = os.environ.get("SCHEMA_VERSION", "1")

# Path to the bundled JSON schema file (packaged in the same directory)
_SCHEMA_FILE = Path(__file__).parent / "sensor_event_schema.json"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------
class SchemaValidationError(ValueError):
    """
    Raised when an incoming event fails canonical schema validation.

    Attributes
    ----------
    message:   Human-readable description of the violation.
    errors:    List of jsonschema.ValidationError instances.
    raw_event: The original (invalid) event dict for dead-letter routing.
    """

    def __init__(
        self,
        message: str,
        errors: list[jsonschema.ValidationError],
        raw_event: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.errors = errors
        self.raw_event = raw_event

    def to_dead_letter_payload(self) -> dict[str, Any]:
        """Serialise to the dead-letter envelope expected by the pipeline."""
        return {
            "raw_event": self.raw_event,
            "validation_errors": [
                {
                    "path": list(e.absolute_path),
                    "message": e.message,
                    "schema_path": list(e.absolute_schema_path),
                }
                for e in self.errors
            ],
            "alert_type": "SCHEMA_VALIDATION_FAILURE",
        }


# ---------------------------------------------------------------------------
# Schema loading & caching
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_local_schema() -> dict[str, Any]:
    """Load the bundled sensor_event_schema.json from disk (cached)."""
    with _SCHEMA_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _compiled_validator() -> jsonschema.Draft7Validator:
    """Return a compiled, cached JSON-Schema Draft-7 validator."""
    schema = _load_local_schema()
    jsonschema.Draft7Validator.check_schema(schema)
    return jsonschema.Draft7Validator(schema)


# ---------------------------------------------------------------------------
# Schema Registry interaction
# ---------------------------------------------------------------------------
def register_schema(
    *,
    registry_url: str = SCHEMA_REGISTRY_URL,
    schema_name: str = SCHEMA_NAME,
    schema_version: str = SCHEMA_VERSION,
    timeout_s: int = 10,
) -> str:
    """
    Register (or update) the canonical sensor-event schema with Apicurio
    Schema Registry.

    Returns the globally-unique schema content hash / ID assigned by the
    registry, or the existing ID if the schema is already registered.

    Raises
    ------
    requests.HTTPError  – on 4xx / 5xx responses.
    requests.Timeout    – if the registry is unreachable within *timeout_s*.
    """
    schema_content = _load_local_schema()

    # Apicurio REST API v2 endpoint
    url = f"{registry_url}/apis/registry/v2/groups/default/artifacts"

    # Try to create the artifact; 409 = already exists, which is fine.
    payload = {
        "artifactId": schema_name,
        "artifactType": "JSON",
        "firstVersion": {
            "version": schema_version,
            "content": json.dumps(schema_content),
            "contentType": "application/json",
        },
    }

    headers = {
        "Content-Type": "application/json",
        "X-Registry-ArtifactId": schema_name,
        "X-Registry-ArtifactType": "JSON",
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=timeout_s,
    )

    if response.status_code == 409:
        # Already registered – fetch the existing global ID
        logger.info(
            "Schema '%s' already registered in Apicurio; verifying version.",
            schema_name,
        )
        meta_url = (
            f"{registry_url}/apis/registry/v2/groups/default/"
            f"artifacts/{schema_name}/meta"
        )
        meta_resp = requests.get(meta_url, timeout=timeout_s)
        meta_resp.raise_for_status()
        global_id: str = str(meta_resp.json().get("globalId", "unknown"))
        logger.info("Existing schema globalId=%s", global_id)
        return global_id

    response.raise_for_status()
    global_id = str(response.json().get("globalId", "created"))
    logger.info(
        "Registered schema '%s' v%s with globalId=%s",
        schema_name,
        schema_version,
        global_id,
    )
    return global_id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_event(event: dict[str, Any]) -> None:
    """
    Validate *event* against the canonical sensor-event JSON schema.

    Raises
    ------
    SchemaValidationError  – if the event violates the schema.
    """
    validator = _compiled_validator()
    errors: list[jsonschema.ValidationError] = sorted(
        validator.iter_errors(event), key=lambda e: list(e.path)
    )

    if errors:
        summary = "; ".join(e.message for e in errors[:3])
        raise SchemaValidationError(
            f"Sensor event failed schema validation: {summary}",
            errors=errors,
            raw_event=event,
        )


def is_valid_event(event: dict[str, Any]) -> bool:
    """Return True if the event passes schema validation, False otherwise."""
    try:
        validate_event(event)
        return True
    except SchemaValidationError:
        return False


# ---------------------------------------------------------------------------
# CLI bootstrap (useful for smoke-testing registration at startup)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gid = register_schema()
    print(f"Schema registered / confirmed. globalId={gid}")
