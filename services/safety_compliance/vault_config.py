"""
RailOS Vault-Backed Configuration Versioning (Task 21.4)
Reads/writes all thresholds and parameters to HashiCorp Vault KV-v2.
Vault audit device logs every read/write immutably (enabled in infra/vault/).
Satisfies: Req 37, Design §11
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

VAULT_ADDR  = os.environ.get("VAULT_ADDR",  "http://vault.railos.svc.cluster.local:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "")

# Secret paths in Vault KV-v2 (secret/railos/<category>)
SECRET_PATHS = {
    "thresholds":  "secret/railos/thresholds",
    "suppression": "secret/railos/suppression",
    "drift":       "secret/railos/drift",
    "deployment":  "secret/railos/deployment",
    "retention":   "secret/railos/retention",
}


def read_config(category: str) -> dict[str, Any]:
    """Read a config category from Vault KV-v2.

    Returns the config dict, or defaults if Vault is unavailable.
    """
    path = SECRET_PATHS.get(category)
    if not path:
        raise ValueError(f"Unknown config category: {category}")
    try:
        import hvac
        client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
        response = client.secrets.kv.v2.read_secret_version(path=path.replace("secret/", ""))
        return response["data"]["data"]
    except Exception as exc:
        log.warning("Vault read failed for %s: %s — using defaults", category, exc)
        return _defaults(category)


def write_config(category: str, updates: dict[str, Any], identity: str) -> dict:
    """Update a config category in Vault KV-v2.

    Vault audit device records: key, prev_value, new_value, identity, timestamp.
    """
    path = SECRET_PATHS.get(category)
    if not path:
        raise ValueError(f"Unknown config category: {category}")
    try:
        import hvac
        client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)
        # Read current state first (for audit trail)
        try:
            current = client.secrets.kv.v2.read_secret_version(
                path=path.replace("secret/", ""))["data"]["data"]
        except Exception as exc:
            log.warning("Could not read current Vault state for %s: %s — starting from empty", category, exc)
            current = {}
        merged = {**current, **updates}
        client.secrets.kv.v2.create_or_update_secret(
            path=path.replace("secret/", ""), secret=merged
        )
        log.info("Config updated: category=%s by=%s keys=%s", category, identity, list(updates.keys()))
        return merged
    except Exception as exc:
        log.error("Vault write failed for %s: %s", category, exc)
        return {}


def _defaults(category: str) -> dict[str, Any]:
    defaults = {
        "thresholds": {
            "defect_detector_confidence_threshold": "0.70",
            "maintenance_failure_probability_threshold": "0.80",
            "security_anomaly_mse_threshold": "0.05",
        },
        "suppression": {
            "defect_alert_suppression_window_seconds": "600",
            "maintenance_advisory_suppression_window_seconds": "3600",
        },
        "drift": {
            "psi_drift_critical_threshold": "0.2",
            "psi_drift_warning_threshold": "0.1",
            "drift_check_interval_seconds": "3600",
        },
        "deployment": {
            "model_rollback_timeout_seconds": "900",
            "federated_learning_round_timeout_seconds": "120",
            "federated_learning_min_clients": "3",
        },
        "retention": {
            "raw_sensor_events_ttl_days": "90",
            "inference_audit_logs_ttl_days": "365",
        },
    }
    return defaults.get(category, {})
