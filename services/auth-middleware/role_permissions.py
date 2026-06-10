"""
RailOS Role-Based Permission Matrix
=====================================
Maps (HTTP method, endpoint pattern) → set of required roles.
Matches Design §9.1 permission matrix exactly.

A request is permitted if the caller's roles overlap with the required set.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import FrozenSet


# ── Role constants ─────────────────────────────────────────────────────────────
OPERATIONS_CONTROLLER = "Operations_Controller"
SECURITY_OFFICER      = "Security_Officer"
ENGINEERING_TEAM      = "Engineering_Team"
GOVERNANCE_OFFICER    = "Governance_Officer"

ALL_ROLES = frozenset({
    OPERATIONS_CONTROLLER,
    SECURITY_OFFICER,
    ENGINEERING_TEAM,
    GOVERNANCE_OFFICER,
})


@dataclass(frozen=True)
class PermissionRule:
    method_pattern: str         # e.g. "POST", "GET", "*"
    path_pattern: str           # regex pattern
    allowed_roles: FrozenSet[str]
    action_description: str


# ── Permission rules — Design §9.1 ────────────────────────────────────────────
# Order matters: first match wins.
PERMISSION_RULES: list[PermissionRule] = [

    # ── Operations_Controller: view and authorize advisories ──────────────────
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/advisories(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER}),
        action_description="view/authorize advisories",
    ),
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/scheduler(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER}),
        action_description="view rescheduling proposals",
    ),
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/digital-twin(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER, ENGINEERING_TEAM}),
        action_description="view digital twin",
    ),

    # ── Security_Officer: acknowledge anomalies, audit, forensic holds ────────
    PermissionRule(
        method_pattern="POST",
        path_pattern=r"^/api/v\d+/anomalies/[^/]+/acknowledge$",
        allowed_roles=frozenset({SECURITY_OFFICER}),
        action_description="acknowledge security anomaly",
    ),
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/forensics(/.*)?$",
        allowed_roles=frozenset({SECURITY_OFFICER}),
        action_description="access forensic evidence",
    ),
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/security(/.*)?$",
        allowed_roles=frozenset({SECURITY_OFFICER}),
        action_description="manage cybersecurity dashboard",
    ),

    # ── Engineering_Team: model deploy/rollback, drift config ─────────────────
    PermissionRule(
        method_pattern="POST",
        path_pattern=r"^/api/v\d+/models/[^/]+/rollback$",
        allowed_roles=frozenset({ENGINEERING_TEAM}),
        action_description="rollback ML model",
    ),
    PermissionRule(
        method_pattern="POST",
        path_pattern=r"^/api/v\d+/models(/.*)?$",
        allowed_roles=frozenset({ENGINEERING_TEAM}),
        action_description="deploy ML model",
    ),
    PermissionRule(
        method_pattern="PUT",
        path_pattern=r"^/api/v\d+/models(/.*)?$",
        allowed_roles=frozenset({ENGINEERING_TEAM}),
        action_description="update ML model configuration",
    ),
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/mlflow(/.*)?$",
        allowed_roles=frozenset({ENGINEERING_TEAM}),
        action_description="access MLflow tracking API",
    ),

    # ── Governance_Officer: lineage reports, retention config, forensic holds ─
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/governance/lineage(/.*)?$",
        allowed_roles=frozenset({GOVERNANCE_OFFICER}),
        action_description="request data lineage report",
    ),
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/retention(/.*)?$",
        allowed_roles=frozenset({GOVERNANCE_OFFICER}),
        action_description="configure retention policies",
    ),
    PermissionRule(
        method_pattern="*",
        path_pattern=r"^/api/v\d+/retention/holds(/.*)?$",
        allowed_roles=frozenset({SECURITY_OFFICER, GOVERNANCE_OFFICER}),
        action_description="manage forensic holds",
    ),

    # ── Audit logs: Security_Officer, Engineering_Team, Governance_Officer ────
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/audit(/.*)?$",
        allowed_roles=frozenset({SECURITY_OFFICER, ENGINEERING_TEAM, GOVERNANCE_OFFICER}),
        action_description="view audit logs",
    ),

    # ── Traceability reports: Engineering_Team + Security_Officer ─────────────
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/traceability(/.*)?$",
        allowed_roles=frozenset({ENGINEERING_TEAM, SECURITY_OFFICER}),
        action_description="view traceability report",
    ),

    # ── Delay predictor + maintenance — Engineering_Team + OC (read) ──────────
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/delay-predictor(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER, ENGINEERING_TEAM}),
        action_description="query delay predictor",
    ),
    PermissionRule(
        method_pattern="POST",
        path_pattern=r"^/api/v\d+/delay-predictor(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER, ENGINEERING_TEAM}),
        action_description="submit delay predictor request",
    ),
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/maintenance(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER, ENGINEERING_TEAM}),
        action_description="view maintenance advisories",
    ),
    PermissionRule(
        method_pattern="GET",
        path_pattern=r"^/api/v\d+/defect-detector(/.*)?$",
        allowed_roles=frozenset({OPERATIONS_CONTROLLER, ENGINEERING_TEAM}),
        action_description="view defect detections",
    ),
]


def get_required_roles(method: str, path: str) -> FrozenSet[str] | None:
    """
    Returns the frozenset of roles that are allowed to make the given request,
    or None if no rule matches (endpoint is public or unregistered).
    First matching rule wins.
    """
    for rule in PERMISSION_RULES:
        method_ok = rule.method_pattern == "*" or rule.method_pattern == method.upper()
        if method_ok and re.match(rule.path_pattern, path):
            return rule.allowed_roles
    return None


def is_permitted(method: str, path: str, caller_roles: set[str]) -> tuple[bool, str]:
    """
    Returns (permitted: bool, reason: str).
    permitted=True if caller has at least one role in the required role set.
    """
    required = get_required_roles(method, path)
    if required is None:
        # No matching rule → endpoint not defined in permission matrix → deny
        return False, f"No permission rule for {method} {path}"
    intersection = frozenset(caller_roles) & required
    if intersection:
        return True, f"Allowed by role(s): {', '.join(sorted(intersection))}"
    return False, (
        f"Role(s) {sorted(caller_roles)} not in required set "
        f"{sorted(required)} for {method} {path}"
    )
