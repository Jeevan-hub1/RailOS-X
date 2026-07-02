"""
RailOS Shared Risk Scoring (Design section 6.2, Tasks 14.1-14.2)
==================================================================
Unified risk-score and risk-tier computation used by the Maintenance
Engine and the Human Authorization Gate.

  riskScore = probability x severity_weight, capped at 4.0
  riskTier:
    Tier 1: riskScore >= 3.2  (dual-auth required)
    Tier 2: 2.0 <= riskScore < 3.2  (single-auth)
    Tier 3: riskScore < 2.0  (standard)
"""
from __future__ import annotations

SEVERITY_WEIGHTS = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
RISK_SCORE_CAP = 4.0


def compute_risk_score(
    probability: float,
    severity_weight: float = SEVERITY_WEIGHTS["HIGH"],
) -> float:
    """Return ``probability * severity_weight``, capped at :data:`RISK_SCORE_CAP`."""
    return min(probability * severity_weight, RISK_SCORE_CAP)


def compute_risk_tier(risk_score: float) -> int:
    """Map a risk score to a tier (1, 2, or 3)."""
    if risk_score >= 3.2:
        return 1
    if risk_score >= 2.0:
        return 2
    return 3
