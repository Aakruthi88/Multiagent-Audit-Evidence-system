from typing import List, Optional, Any
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, UUID4


class VerificationCheckOut(BaseModel):
    check_id: UUID4
    check_type: str
    status: str                     # pass | warning | fail | not_applicable
    expected_value: Optional[str]
    actual_value: Optional[str]
    variance: Optional[Decimal]
    severity: Optional[str]
    explanation: str

    model_config = {"from_attributes": True}


class DiscrepancyOut(BaseModel):
    discrepancy_id: UUID4
    check_id: Optional[UUID4]
    category: str
    severity: str                   # low | medium | high | critical
    description: str
    recommended_action: Optional[str]
    resolved: bool

    model_config = {"from_attributes": True}


class VerificationRunOut(BaseModel):
    run_id: UUID4
    bundle_id: UUID4
    started_at: datetime
    completed_at: Optional[datetime]
    overall_status: Optional[str]   # clean | flagged | critical | incomplete
    overall_risk_score: Optional[Decimal]
    rules_version: str
    checks: List[VerificationCheckOut]
    discrepancies: List[DiscrepancyOut]

    model_config = {"from_attributes": True}


class VerificationTriggerResponse(BaseModel):
    bundle_id: str
    run_id: Optional[str]
    overall_status: Optional[str]
    overall_risk_score: Optional[float]
    total_checks: int
    total_discrepancies: int
    critical_count: int
    high_count: int
    needs_investigation: bool
    message: str
