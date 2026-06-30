"""
End-to-end RBAC matrix integration test.

Exercises the REAL authorization logic (services.auth_middleware.role_permissions)
across all four roles against representative endpoints, asserting the
permission matrix from Design 9.1 holds — both the allow and the deny paths,
including the "unregistered endpoint is denied by default" rule.
"""
from __future__ import annotations

import pytest

from services.auth_middleware.role_permissions import (
    is_permitted,
    OPERATIONS_CONTROLLER,
    SECURITY_OFFICER,
    ENGINEERING_TEAM,
    GOVERNANCE_OFFICER,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "method,path,roles,expected",
    [
        # Operations Controller — advisories / scheduler
        ("POST", "/api/v1/advisories/abc/authorize", {OPERATIONS_CONTROLLER}, True),
        ("POST", "/api/v1/advisories/abc/authorize", {SECURITY_OFFICER}, False),
        ("GET", "/api/v1/scheduler/proposals", {OPERATIONS_CONTROLLER}, True),
        # Engineering — model rollback (and OC must NOT be able to)
        ("POST", "/api/v1/models/m1/rollback", {ENGINEERING_TEAM}, True),
        ("POST", "/api/v1/models/m1/rollback", {OPERATIONS_CONTROLLER}, False),
        # Security Officer — anomaly acknowledge
        ("POST", "/api/v1/anomalies/x/acknowledge", {SECURITY_OFFICER}, True),
        ("POST", "/api/v1/anomalies/x/acknowledge", {OPERATIONS_CONTROLLER}, False),
        # Governance — retention; audit is shared across three roles
        ("GET", "/api/v1/governance/lineage/report", {GOVERNANCE_OFFICER}, True),
        ("GET", "/api/v1/audit/log", {GOVERNANCE_OFFICER}, True),
        ("GET", "/api/v1/audit/log", {OPERATIONS_CONTROLLER}, False),
        # Digital twin viewable by OC and Engineering
        ("GET", "/api/v1/digital-twin/state", {ENGINEERING_TEAM}, True),
        # Unregistered endpoint → denied by default
        ("GET", "/api/v1/unknown/thing", {GOVERNANCE_OFFICER}, False),
    ],
)
def test_permission_matrix(method, path, roles, expected):
    permitted, reason = is_permitted(method, path, roles)
    assert permitted is expected, f"{method} {path} with {roles}: {reason}"


def test_multi_role_caller_gets_union_of_permissions():
    # A caller holding two roles should be permitted wherever either role is.
    roles = {OPERATIONS_CONTROLLER, ENGINEERING_TEAM}
    assert is_permitted("POST", "/api/v1/models/m1/rollback", roles)[0]      # Eng
    assert is_permitted("POST", "/api/v1/advisories/x/authorize", roles)[0]  # OC
