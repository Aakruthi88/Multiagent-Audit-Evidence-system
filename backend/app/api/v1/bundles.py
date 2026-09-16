import re
from decimal import Decimal
from typing import Optional, List
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_bundle_access, require_auditor
from app.core.config import settings
from app.db.session import get_db
from app.models.models import (
    AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement,
    AgentExecutionLog, User, VerificationRun, VerificationCheck, Discrepancy
)
from app.schemas.bundle_schemas import (
    BundleCreateResponse, BundleDetailResponse, DocumentResponse, AgentLogResponse
)
from app.services.storage_service import storage_service
from app.services.report_export_service import report_export_service
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
    current_user: User = Depends(require_auditor),
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
    Binds bundle ownership to the authenticated user.
    """
    # Check if bundle with this txn_reference already exists
    existing = db.query(AuditBundle).filter(AuditBundle.txn_reference == txn_reference).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audit bundle with transaction reference '{txn_reference}' already exists."
        )

    # 1. Create Audit Bundle bound to authenticated user
    bundle = AuditBundle(
        txn_reference=txn_reference,
        status="uploaded",
        uploaded_by=current_user.user_id,
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
    logger.info(
        f"[Bundles] Created bundle {bundle.bundle_id} ({txn_reference}) "
        f"by user '{current_user.email}' with {len(created_docs)} documents."
    )

    return bundle


@router.get("", response_model=List[BundleDetailResponse])
def list_bundles(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    GET /api/v1/bundles - List audit bundles.
    Client Isolation: Auditors only see bundles they uploaded (or unassigned demo bundles).
    Lead role sees all bundles.
    """
    q = db.query(AuditBundle)
    user_role = (current_user.role or "auditor").lower().strip()
    if user_role != "lead":
        q = q.filter(
            (AuditBundle.uploaded_by == current_user.user_id) | (AuditBundle.uploaded_by == None)
        )

    bundles = q.order_by(AuditBundle.created_at.desc()).offset(skip).limit(limit).all()
    return bundles


@router.get("/metrics/impact")
def get_business_impact_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    GET /api/v1/bundles/metrics/impact
    Calculates Business Impact & ROI metrics based strictly on REAL database records.
    Scopes calculations by user role (Lead: all bundles; Auditor: user's bundles + demo).
    """
    user_role = (current_user.role or "auditor").lower().strip()
    bundle_q = db.query(AuditBundle)
    if user_role != "lead":
        bundle_q = bundle_q.filter(
            (AuditBundle.uploaded_by == current_user.user_id) | (AuditBundle.uploaded_by == None)
        )
    
    bundles = bundle_q.all()
    bundle_ids = [b.bundle_id for b in bundles]

    total_bundles = len(bundles)
    verified_bundles = sum(1 for b in bundles if str(b.status).lower() in ("verified", "clean", "reported"))
    flagged_bundles = sum(1 for b in bundles if str(b.status).lower() in ("flagged", "critical", "failed"))
    incomplete_bundles = sum(1 for b in bundles if str(b.status).lower() in ("incomplete", "uploaded", "pending"))

    if not bundle_ids:
        return {
            "total_bundles_audited": 0,
            "total_documents_processed": 0,
            "total_verification_checks": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "checks_warning": 0,
            "total_exceptions_detected": 0,
            "critical_exceptions": 0,
            "high_exceptions": 0,
            "total_transaction_value_reviewed": 0.0,
            "total_discrepancy_variance_identified": 0.0,
            "estimated_manual_hours_saved": 0.0,
            "roi_benchmark_assumptions": {
                "minutes_per_document_manual_review": 15,
                "minutes_per_cross_matching_check": 2,
                "basis": "Standard Big-4 audit manual review benchmark: 15 min per document ingestion/inspection + 2 min per 4-way matching rule comparison."
            }
        }

    # Total documents processed
    docs = db.query(Document).filter(Document.bundle_id.in_(bundle_ids)).all()
    total_docs = len(docs)
    extracted_docs = sum(1 for d in docs if d.extraction_status == "success")

    # Verification runs and checks
    runs = db.query(VerificationRun).filter(VerificationRun.bundle_id.in_(bundle_ids)).all()
    run_ids = [r.run_id for r in runs]

    checks = []
    discrepancies = []
    if run_ids:
        checks = db.query(VerificationCheck).filter(VerificationCheck.run_id.in_(run_ids)).all()
        discrepancies = db.query(Discrepancy).filter(Discrepancy.run_id.in_(run_ids)).all()

    total_checks = len(checks)
    checks_passed = sum(1 for c in checks if c.status == "pass")
    checks_failed = sum(1 for c in checks if c.status == "fail")
    checks_warning = sum(1 for c in checks if c.status == "warning")

    total_exceptions = len(discrepancies)
    critical_exceptions = sum(1 for d in discrepancies if d.severity == "critical")
    high_exceptions = sum(1 for d in discrepancies if d.severity == "high")

    # Financial totals reviewed
    invoices = db.query(Invoice).filter(Invoice.bundle_id.in_(bundle_ids)).all()
    pos = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id.in_(bundle_ids)).all()
    
    total_val = sum(float(i.total_amount or 0.0) for i in invoices)
    if total_val == 0.0:
        total_val = sum(float(p.total_amount or 0.0) for p in pos)

    # Discrepancy variance total
    total_variance = sum(float(c.variance or 0.0) for c in checks if c.variance is not None and c.status == "fail")

    # Estimated manual time avoided
    # Assumption: 15 min per document + 2 min per check = total minutes / 60
    saved_minutes = (extracted_docs * 15) + (total_checks * 2)
    saved_hours = round(saved_minutes / 60.0, 1)

    return {
        "total_bundles_audited": total_bundles,
        "verified_bundles": verified_bundles,
        "flagged_bundles": flagged_bundles,
        "incomplete_bundles": incomplete_bundles,
        "total_documents_processed": total_docs,
        "extracted_documents": extracted_docs,
        "total_verification_checks": total_checks,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "checks_warning": checks_warning,
        "total_exceptions_detected": total_exceptions,
        "critical_exceptions": critical_exceptions,
        "high_exceptions": high_exceptions,
        "total_transaction_value_reviewed": round(total_val, 2),
        "total_discrepancy_variance_identified": round(total_variance, 2),
        "estimated_manual_hours_saved": saved_hours,
        "roi_benchmark_assumptions": {
            "minutes_per_document_manual_review": 15,
            "minutes_per_cross_matching_check": 2,
            "basis": "Standard Big-4 audit manual review benchmark: 15 min per document ingestion/inspection + 2 min per 4-way matching rule comparison."
        }
    }


@router.get("/{bundle_id}", response_model=BundleDetailResponse)
def get_bundle(
    bundle_id: UUID,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles/{bundle_id} - Fetch details of a specific authorized bundle."""
    # Compile extracted summary if available
    extracted_summary = {}
    po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle.bundle_id).first()
    if po:
        extracted_summary["purchase_order"] = {"po_number": po.po_number, "total_amount": float(po.total_amount)}
    inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
    if inv:
        extracted_summary["invoice"] = {"invoice_number": inv.invoice_number, "total_amount": float(inv.total_amount)}
    grn = db.query(GRN).filter(GRN.bundle_id == bundle.bundle_id).first()
    if grn:
        extracted_summary["grn"] = {"grn_number": grn.grn_number, "total_amount": float(grn.total_amount)}
    bs = db.query(BankStatement).filter(BankStatement.bundle_id == bundle.bundle_id).first()
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
    bundle: AuditBundle = Depends(verify_bundle_access)
):
    """GET /api/v1/bundles/{bundle_id}/status - Lightweight status check endpoint."""
    return {"bundle_id": bundle.bundle_id, "status": bundle.status}


@router.get("/{bundle_id}/trace", response_model=List[AgentLogResponse])
def get_bundle_trace(
    bundle_id: UUID,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """GET /api/v1/bundles/{bundle_id}/trace - Retrieve execution trace for Agent Trace UI."""
    logs = (
        db.query(AgentExecutionLog)
        .filter(AgentExecutionLog.bundle_id == bundle.bundle_id)
        .order_by(AgentExecutionLog.created_at.asc())
        .all()
    )
    return logs


@router.get("/{bundle_id}/extraction-review")
def get_extraction_review(
    bundle_id: UUID,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """
    GET /api/v1/bundles/{bundle_id}/extraction-review
    Returns comprehensive extraction debug information per document in the bundle.
    """
    reviews = []
    for doc in bundle.documents:
        # Find latest execution log for this document type
        log = (
            db.query(AgentExecutionLog)
            .filter(
                AgentExecutionLog.bundle_id == bundle.bundle_id,
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
        "bundle_id": str(bundle.bundle_id),
        "status": bundle.status,
        "document_reviews": reviews
    }


@router.get("/{bundle_id}/files")
def list_bundle_files(
    bundle_id: UUID,
    bundle: AuditBundle = Depends(verify_bundle_access)
):
    """
    GET /api/v1/bundles/{bundle_id}/files
    Discovers and lists existing PDF files stored in storage/bundles/{bundle_id}/.
    """
    bundle_dir = (settings.STORAGE_DIR / "bundles" / str(bundle.bundle_id)).resolve()
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        return {"bundle_id": str(bundle.bundle_id), "files": []}

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
            "url": f"{settings.API_V1_STR}/bundles/{bundle.bundle_id}/files/{fname}"
        })

    order = {"invoice": 1, "purchase_order": 2, "grn": 3, "bank_statement": 4}
    files.sort(key=lambda x: (order.get(x["doc_type"], 99), x["filename"]))

    return {"bundle_id": str(bundle.bundle_id), "files": files}


@router.get("/{bundle_id}/files/{filename}")
def get_bundle_file(
    bundle_id: UUID,
    filename: str,
    bundle: AuditBundle = Depends(verify_bundle_access)
):
    """
    GET /api/v1/bundles/{bundle_id}/files/{filename}
    Safely serves the existing PDF file from storage/bundles/{bundle_id}/.
    Enforces authorization and strict path traversal protection.
    """
    # Strict filename validation
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal characters detected."
        )

    if not re.match(r'^[a-zA-Z0-9_\-\.]+\.pdf$', filename, re.IGNORECASE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename format or unsupported file extension."
        )

    bundle_dir = (settings.STORAGE_DIR / "bundles" / str(bundle.bundle_id)).resolve()
    target_file = (bundle_dir / filename).resolve()

    # Verify path containment
    if not str(target_file).startswith(str(bundle_dir)) or not target_file.is_file():
        raise HTTPException(status_code=404, detail="Requested document file not found")

    return FileResponse(
        path=str(target_file),
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline"
    )


@router.get("/{bundle_id}/export-workpaper")
def export_audit_workpaper(
    bundle_id: UUID,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """
    GET /api/v1/bundles/{bundle_id}/export-workpaper
    Generates and returns a professional, deterministic Audit Workpaper PDF.
    - Protected by JWT authentication and RBAC bundle access isolation.
    - Generated strictly from database records (never queries LLMs for audit values).
    - Returns application/pdf with Content-Disposition attachment header.
    """
    try:
        pdf_bytes = report_export_service.generate_workpaper_pdf(db, bundle)
        filename = f"audit_workpaper_{bundle.txn_reference}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/pdf"
            }
        )
    except Exception as exc:
        logger.exception(f"[WorkpaperExport] Error generating workpaper PDF for bundle {bundle.bundle_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate audit workpaper: {str(exc)}"
        )
