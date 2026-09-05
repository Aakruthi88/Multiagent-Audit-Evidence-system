from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel

class DocumentResponse(BaseModel):
    document_id: UUID
    bundle_id: UUID
    doc_type: str
    file_path: str
    file_hash: str
    extraction_status: str
    extraction_confidence: Optional[float] = None
    extraction_model: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True

class DocumentDetailResponse(DocumentResponse):
    raw_text: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None

class BundleCreateResponse(BaseModel):
    bundle_id: UUID
    txn_reference: str
    status: str
    created_at: datetime
    documents: List[DocumentResponse] = []

    class Config:
        from_attributes = True

class BundleDetailResponse(BaseModel):
    bundle_id: UUID
    txn_reference: str
    status: str
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentResponse] = []
    extracted_summary: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

class AgentLogResponse(BaseModel):
    log_id: UUID
    run_id: Optional[UUID] = None
    bundle_id: Optional[UUID] = None
    agent_name: str
    input_snapshot: Optional[Dict[str, Any]] = None
    output_snapshot: Optional[Dict[str, Any]] = None
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    latency_ms: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
