"""
Integration tests: Task 15.5
Verify each role CANNOT perform actions outside its defined permission scope.
Verify each role CAN perform its allowed actions.

Run:
    pytest services/auth-middleware/tests/test_auth_middleware.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from role_permissions import is_permitted, OPERATIONS_CONTROLLER, SECURITY_OFFICER, \
    ENGINEERING_TEAM, GOVERNANCE_OFFICER


# ── Helpers ────────────────────────────────────────────────────────────────────

def allow(method, path, *roles):
    ok, reason = is_permitted(method, path, set(roles))
    return ok, reason


def deny(method, path, *roles):
    ok, reason = is_permitted(method, path, set(roles))
    return not ok, reason


# ── Operations_Controller scope ───────────────────────────────────────────────

class TestOperationsController:

    def test_can_view_advisories(self):
        ok, reason = allow("GET", "/api/v1/advisories", OPERATIONS_CONTROLLER)
        assert ok, f"OC should view advisories: {reason}"

    def test_can_authorize_advisory(self):
        ok, reason = allow("POST", "/api/v1/advisories/abc123/authorize", OPERATIONS_CONTROLLER)
        assert ok, f"OC should authorize advisories: {reason}"

    def test_cannot_deploy_model(self):
        """Task 15.5: OC must NOT be able to deploy ML models."""
        denied, reason = deny("POST", "/api/v1/models/deploy", OPERATIONS_CONTROLLER)
        assert denied, f"OC should NOT deploy models but was allowed: {reason}"

    def test_cannot_acknowledge_security_anomaly(self):
        """Task 15.5: OC must NOT acknowledge security anomalies (Security_Officer only)."""
        denied, reason = deny("POST", "/api/v1/anomalies/xyz/acknowledge", OPERATIONS_CONTROLLER)
        assert denied, f"OC should NOT acknowledge anomalies but was allowed: {reason}"

    def test_cannot_configure_retention(self):
        """Task 15.5: OC must NOT configure data retention policies."""
        denied, reason = deny("PUT", "/api/v1/retention/config", OPERATIONS_CONTROLLER)
        assert denied, f"OC should NOT configure retention but was allowed: {reason}"

    def test_cannot_access_forensics(self):
        """Task 15.5: OC must NOT access forensic evidence."""
        denied, reason = deny("GET", "/api/v1/forensics/alert-abc", OPERATIONS_CONTROLLER)
        assert denied, f"OC should NOT access forensics but was allowed: {reason}"

    def test_cannot_rollback_model(self):
        """Task 15.5: OC must NOT rollback ML models."""
        denied, reason = deny("POST", "/api/v1/models/defect_detector/rollback", OPERATIONS_CONTROLLER)
        assert denied, f"OC should NOT rollback models but was allowed: {reason}"


# ── Security_Officer scope ────────────────────────────────────────────────────

class TestSecurityOfficer:

    def test_can_acknowledge_anomaly(self):
        ok, reason = allow("POST", "/api/v1/anomalies/xyz/acknowledge", SECURITY_OFFICER)
        assert ok, f"SO should acknowledge anomalies: {reason}"

    def test_can_view_audit_log(self):
        ok, reason = allow("GET", "/api/v1/audit/events", SECURITY_OFFICER)
        assert ok, f"SO should view audit logs: {reason}"

    def test_can_access_forensics(self):
        ok, reason = allow("GET", "/api/v1/forensics/alert-abc/package", SECURITY_OFFICER)
        assert ok, f"SO should access forensics: {reason}"

    def test_cannot_authorize_advisory(self):
        """Task 15.5: SO must NOT authorize operational advisories (OC only)."""
        denied, reason = deny("POST", "/api/v1/advisories/abc/authorize", SECURITY_OFFICER)
        assert denied, f"SO should NOT authorize advisories but was allowed: {reason}"

    def test_cannot_deploy_model(self):
        """Task 15.5: SO must NOT deploy ML models."""
        denied, reason = deny("POST", "/api/v1/models/new", SECURITY_OFFICER)
        assert denied, f"SO should NOT deploy models but was allowed: {reason}"

    def test_cannot_configure_retention(self):
        """Task 15.5: SO must NOT configure retention policies (Governance_Officer only)."""
        denied, reason = deny("PUT", "/api/v1/retention/policy", SECURITY_OFFICER)
        assert denied, f"SO should NOT configure retention but was allowed: {reason}"


# ── Engineering_Team scope ────────────────────────────────────────────────────

class TestEngineeringTeam:

    def test_can_rollback_model(self):
        ok, reason = allow("POST", "/api/v1/models/defect_detector/rollback", ENGINEERING_TEAM)
        assert ok, f"ET should rollback models: {reason}"

    def test_can_deploy_model(self):
        ok, reason = allow("POST", "/api/v1/models/defect_detector", ENGINEERING_TEAM)
        assert ok, f"ET should deploy models: {reason}"

    def test_can_view_audit_log(self):
        ok, reason = allow("GET", "/api/v1/audit/inference", ENGINEERING_TEAM)
        assert ok, f"ET should view audit logs: {reason}"

    def test_can_access_mlflow(self):
        ok, reason = allow("GET", "/api/v1/mlflow/experiments", ENGINEERING_TEAM)
        assert ok, f"ET should access MLflow: {reason}"

    def test_cannot_acknowledge_anomaly(self):
        """Task 15.5: ET must NOT acknowledge security anomalies."""
        denied, reason = deny("POST", "/api/v1/anomalies/xyz/acknowledge", ENGINEERING_TEAM)
        assert denied, f"ET should NOT acknowledge anomalies but was allowed: {reason}"

    def test_cannot_authorize_advisory(self):
        """Task 15.5: ET must NOT authorize operational advisories."""
        denied, reason = deny("POST", "/api/v1/advisories/abc/authorize", ENGINEERING_TEAM)
        assert denied, f"ET should NOT authorize advisories but was allowed: {reason}"

    def test_cannot_configure_retention(self):
        """Task 15.5: ET must NOT configure retention policies."""
        denied, reason = deny("DELETE", "/api/v1/retention/policy", ENGINEERING_TEAM)
        assert denied, f"ET should NOT configure retention but was allowed: {reason}"


# ── Governance_Officer scope ──────────────────────────────────────────────────

class TestGovernanceOfficer:

    def test_can_request_lineage_report(self):
        ok, reason = allow("GET", "/api/v1/governance/lineage/dataset-xyz", GOVERNANCE_OFFICER)
        assert ok, f"GO should request lineage reports: {reason}"

    def test_can_configure_retention(self):
        ok, reason = allow("PUT", "/api/v1/retention/sensor_events", GOVERNANCE_OFFICER)
        assert ok, f"GO should configure retention policies: {reason}"

    def test_can_manage_forensic_holds(self):
        ok, reason = allow("POST", "/api/v1/retention/holds", GOVERNANCE_OFFICER)
        assert ok, f"GO should manage forensic holds: {reason}"

    def test_can_view_audit_logs(self):
        ok, reason = allow("GET", "/api/v1/audit/governance", GOVERNANCE_OFFICER)
        assert ok, f"GO should view audit logs: {reason}"

    def test_cannot_authorize_advisory(self):
        """Task 15.5: GO must NOT authorize operational advisories."""
        denied, reason = deny("POST", "/api/v1/advisories/abc/authorize", GOVERNANCE_OFFICER)
        assert denied, f"GO should NOT authorize advisories but was allowed: {reason}"

    def test_cannot_deploy_model(self):
        """Task 15.5: GO must NOT deploy ML models."""
        denied, reason = deny("POST", "/api/v1/models/new", GOVERNANCE_OFFICER)
        assert denied, f"GO should NOT deploy models but was allowed: {reason}"

    def test_cannot_acknowledge_anomaly(self):
        """Task 15.5: GO must NOT acknowledge security anomalies."""
        denied, reason = deny("POST", "/api/v1/anomalies/xyz/acknowledge", GOVERNANCE_OFFICER)
        assert denied, f"GO should NOT acknowledge anomalies but was allowed: {reason}"


# ── Cross-role boundary checks ────────────────────────────────────────────────

class TestRoleBoundaries:
    """Verifies no role can perform every action (no privilege escalation via overlap)."""

    def test_no_single_role_can_do_everything(self):
        critical_actions = [
            ("POST", "/api/v1/advisories/x/authorize"),
            ("POST", "/api/v1/anomalies/x/acknowledge"),
            ("POST", "/api/v1/models/x/rollback"),
            ("GET",  "/api/v1/governance/lineage/x"),
        ]
        all_roles = [OPERATIONS_CONTROLLER, SECURITY_OFFICER, ENGINEERING_TEAM, GOVERNANCE_OFFICER]
        for role in all_roles:
            allowed_count = sum(
                1 for method, path in critical_actions
                if is_permitted(method, path, {role})[0]
            )
            assert allowed_count < len(critical_actions), (
                f"Role {role} can perform all critical actions — privilege escalation risk"
            )

    def test_endpoint_with_no_rule_is_denied(self):
        """Endpoints not in the permission matrix should be denied."""
        denied, reason = deny("DELETE", "/api/v1/unknown-endpoint", OPERATIONS_CONTROLLER)
        assert denied, "Unknown endpoints must be denied by default"
