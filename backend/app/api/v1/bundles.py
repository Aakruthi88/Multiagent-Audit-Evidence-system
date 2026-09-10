from typing import Optional, List
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.models import (
    AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement, AgentExecutionLog
)
from app.schemas.bundle_schemas import (
    BundleCreateResponse, BundleDetailResponse, DocumentResponse, AgentLogResponse
)
from app.services.storage_service import storage_service
from app.workers.tasks import process_bundle_task
from app.core.logging import logger

router = APIRouter(prefix="/bundles", tags=["bundles"])

@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=BundleCreateResponse)
def create_bundle(
    background_tasks: BackgroundTasks,
    txn_reference: str = Form(...),
    purchase_order: Optional[UploadFile] = File(None),
    invoice: Optional[UploadFile] = File(None),
    grn: Optional[UploadFile] = File(None),
    bank_statement: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """
    POST /api/v1/bundles
    Creates an audit bundle and saves uploaded PDF files for:
    - Purchase Order
    - Invoice
    - Goods Received Note (GRN)
    - Bank Statement
    Enqueues background task for LangGraph extraction pipeline.
    """
    # Check if bundle with this txn_reference already exists
    existing = db.query(AuditBundle).filter(AuditBundle.txn_reference == txn_reference).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audit bundle with transaction reference '{txn_reference}' already exists."
        )

    # 1. Create Audit Bundle
    bundle = AuditBundle(
        txn_reference=txn_reference,
        status="uploaded"
    )
    db.add(bundle)
    db.flush()

    files_map = {
        "purchase_order": purchase_order,
        "invoice": invoice,
        "grn": grn,
        "bank_statement": bank_statement
    }

    doc_paths = {}
    created_docs = []

    # 2. Save Uploaded Files and create Document records
    for doc_type, upload_file in files_map.items():
        if upload_file:
            file_path, file_hash = storage_service.save_bundle_file(
                bundle_id=str(bundle.bundle_id),
                doc_type=doc_type,
                file=upload_file
            )
            doc_paths[doc_type] = file_path

            doc = Document(
                bundle_id=bundle.bundle_id,
                doc_type=doc_type,
                file_path=file_path,
                file_hash=file_hash,
                extraction_status="pending"
            )
            db.add(doc)
            db.flush()
            created_docs.append(doc)

    db.commit()
    db.refresh(bundle)

    # 3. Enqueue Background Task for LangGraph Execution
    background_tasks.add_task(process_bundle_task, str(bundle.bundle_id), doc_paths)
    logger.info(f"Created bundle {bundle.bundle_id} ({txn_reference}) with {len(created_docs)} documents.")

    return bundle

@router.get("", response_model=List[BundleDetailResponse])
def list_bundles(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles - List all audit bundles."""
    bundles = db.query(AuditBundle).order_by(AuditBundle.created_at.desc()).offset(skip).limit(limit).all()
    return bundles

@router.get("/{bundle_id}", response_model=BundleDetailResponse)
def get_bundle(
    bundle_id: UUID,
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles/{bundle_id} - Fetch details of a specific bundle."""
    bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
    if not bundle:
        raise HTTPException(status_code=404, detail="Audit bundle not found")
    
    # Compile extracted summary if available
    extracted_summary = {}
    po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle_id).first()
    if po:
        extracted_summary["purchase_order"] = {"po_number": po.po_number, "total_amount": float(po.total_amount)}
    inv = db.query(Invoice).filter(Invoice.bundle_id == bundle_id).first()
    if inv:
        extracted_summary["invoice"] = {"invoice_number": inv.invoice_number, "total_amount": float(inv.total_amount)}
    grn = db.query(GRN).filter(GRN.bundle_id == bundle_id).first()
    if grn:
        extracted_summary["grn"] = {"grn_number": grn.grn_number, "total_amount": float(grn.total_amount)}
    bs = db.query(BankStatement).filter(BankStatement.bundle_id == bundle_id).first()
    if bs:
        extracted_summary["bank_statement"] = {"account_number": bs.account_number}

    res_dict = {
        "bundle_id": bundle.bundle_id,
        "txn_reference": bundle.txn_reference,
        "status": bundle.status,
        "created_at": bundle.created_at,
        "updated_at": bundle.updated_at,
        "documents": bundle.documents,
        "extracted_summary": extracted_summary
    }
    return res_dict

@router.get("/{bundle_id}/status")
def get_bundle_status(
    bundle_id: UUID,
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles/{bundle_id}/status - Lightweight status check endpoint."""
    bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
    if not bundle:
        raise HTTPException(status_code=404, detail="Audit bundle not found")
    return {"bundle_id": bundle.bundle_id, "status": bundle.status}

@router.get("/{bundle_id}/trace", response_model=List[AgentLogResponse])
def get_bundle_trace(
    bundle_id: UUID,
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles/{bundle_id}/trace - Retrieve execution trace for Agent Trace UI."""
    logs = db.query(AgentExecutionLog).filter(AgentExecutionLog.bundle_id == bundle_id).order_by(AgentExecutionLog.created_at.asc()).all()
    return logs

@router.get("/{bundle_id}/extraction-review")
def get_extraction_review(
    bundle_id: UUID,
    db: Session = Depends(get_db)
):
    """
    GET /api/v1/bundles/{bundle_id}/extraction-review
    Returns comprehensive extraction debug information per document in the bundle:
      - raw_text
      - prompt
      - raw_llm_response
      - parsed_json
      - validation_errors
      - retry_response
      - confidence score & model used
    """
    bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
    if not bundle:
        raise HTTPException(status_code=404, detail="Audit bundle not found")

    reviews = []
    for doc in bundle.documents:
        # Find latest execution log for this document type
        log = (
            db.query(AgentExecutionLog)
            .filter(
                AgentExecutionLog.bundle_id == bundle_id,
                AgentExecutionLog.agent_name == f"document_understanding_{doc.doc_type}"
            )
            .order_by(AgentExecutionLog.created_at.desc())
            .first()
        )

        log_input = log.input_snapshot if log else {}
        log_output = log.output_snapshot if log else {}

        reviews.append({
            "document_id": str(doc.document_id),
            "doc_type": doc.doc_type,
            "extraction_status": doc.extraction_status,
            "extraction_confidence": doc.extraction_confidence,
            "extraction_model": doc.extraction_model,
            "raw_text": doc.raw_text,
            "debug": {
                "prompt": log_input.get("prompt"),
                "cleaned_text": log_input.get("cleaned_text"),
                "raw_llm_response": log_output.get("raw_llm_response"),
                "parsed_json": log_output.get("parsed_json"),
                "validation_errors": log_output.get("validation_errors"),
                "retry_attempted": log_output.get("retry_attempted", False),
                "retry_response": log_output.get("retry_response"),
                "numeric_validation_passed": log_output.get("numeric_validation_passed", False),
                "warnings": log_output.get("warnings", []),
                "extracted_data": log_output.get("extracted_data"),
                "latency_ms": log.latency_ms if log else None,
                "tokens_used": log.tokens_used if log else 0,
            }
        })

    return {
        "bundle_id": str(bundle_id),
        "status": bundle.status,
        "document_reviews": reviews
    }


@router.get("/{bundle_id}/files")
def list_bundle_files(
    bundle_id: UUID
):
    """
    GET /api/v1/bundles/{bundle_id}/files
    Discovers and lists existing PDF files stored in storage/bundles/{bundle_id}/.
    """
    bundle_dir = (settings.STORAGE_DIR / "bundles" / str(bundle_id)).resolve()
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        return {"bundle_id": str(bundle_id), "files": []}

    DOC_TYPE_LABELS = {
        "invoice": "Invoice",
        "purchase_order": "Purchase Order",
        "grn": "GRN",
        "bank_statement": "Bank Statement"
    }

    files = []
    for file_path in bundle_dir.glob("*.pdf"):
        fname = file_path.name
        matched_label = None
        matched_type = None
        for dtype, label in DOC_TYPE_LABELS.items():
            if fname.startswith(f"{dtype}_") or dtype in fname.lower():
                matched_label = label
                matched_type = dtype
                break
        if not matched_label:
            matched_label = fname.replace(".pdf", "").replace("_", " ").title()
            matched_type = "document"

        files.append({
            "filename": fname,
            "doc_type": matched_type,
            "label": matched_label,
            "size_bytes": file_path.stat().st_size,
            "url": f"{settings.API_V1_STR}/bundles/{bundle_id}/files/{fname}"
        })

    order = {"invoice": 1, "purchase_order": 2, "grn": 3, "bank_statement": 4}
    files.sort(key=lambda x: (order.get(x["doc_type"], 99), x["filename"]))

    return {"bundle_id": str(bundle_id), "files": files}


@router.get("/{bundle_id}/files/{filename}")
def get_bundle_file(
    bundle_id: UUID,
    filename: str
):
    """
    GET /api/v1/bundles/{bundle_id}/files/{filename}
    Safely serves the existing PDF file from storage/bundles/{bundle_id}/.
    """
    bundle_dir = (settings.STORAGE_DIR / "bundles" / str(bundle_id)).resolve()
    target_file = (bundle_dir / filename).resolve()

    if not str(target_file).startswith(str(bundle_dir)) or not target_file.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(target_file),
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline"
    )


