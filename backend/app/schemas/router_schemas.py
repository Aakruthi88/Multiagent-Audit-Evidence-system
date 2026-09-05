from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class RouterDecision(BaseModel):
    user_intent: str = Field(
        ...,
        description="Core intent: 'upload_and_extract' | 'verify_bundle' | 'investigate_discrepancies' | 'generate_report' | 'ask_clarification'"
    )
    target_workflow: str = Field(
        ...,
        description="Downstream workflow node target: 'document_understanding' | 'verification' | 'search_investigation' | 'report_generation' | 'clarification'"
    )
    txn_reference: Optional[str] = Field(
        None,
        description="Transaction reference extracted from query e.g. TXN-2026-001 or TXN-2026-006"
    )
    bundle_id: Optional[str] = Field(
        None,
        description="Bundle UUID if referenced"
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted parameters e.g. vendor_name, date_range, severity, doc_type"
    )
    confidence: float = Field(
        ...,
        description="Confidence score between 0.0 and 1.0"
    )
    requires_clarification: bool = Field(
        default=False,
        description="True if query is ambiguous or missing required target information"
    )
    clarification_message: Optional[str] = Field(
        None,
        description="Message to return to user if clarification is required"
    )
    explanation: str = Field(
        ...,
        description="Short reasoning for the routing decision"
    )

class RouterClassifyRequest(BaseModel):
    user_query: str = Field(..., description="Natural language user prompt")
    bundle_id: Optional[str] = Field(None, description="Optional current bundle ID context")
