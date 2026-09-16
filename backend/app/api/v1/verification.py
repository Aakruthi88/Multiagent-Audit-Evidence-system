"""
Verification API - backend/app/api/v1/verification.py
-----------------------------------------------------
POST /api/v1/verification/run/{bundle_id}  → Trigger synchronous 4-way match check
GET  /api/v1/verification/{run_id}         → Retrieve a specific verification run
GET  /api/v1/verification/bundle/{bundle_id}/latest → Latest run for a bundle
GET  /api/v1/verification/bundle/{bundle_id}/all    → All runs for a bundle
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, verify_bundle_access
from app.db.session import get_db
from app.models.models import (
    AuditBundle, VerificationRun, VerificationCheck, Discrepancy, User
)
from app.schemas.verification_schemas import (
    VerificationRunOut, VerificationTriggerResponse
)
from app.services.verification_service import verification_service
from app.core.logging import logger

router = APIRouter(prefix="/verification", tags=["verification"])


@router.post("/run/{bundle_id}", response_model=VerificationTriggerResponse)
def trigger_verification(
    bundle_id: str,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """
    Trigger deterministic 4-way match verification for an authorized bundle.
    Synchronous — waits for all checks to complete before responding.
    The LLM is NOT called here. All logic is deterministic Python.
    """
    # Check all documents have been extracted
    docs = bundle.documents
    extracted_types = {d.doc_type for d in docs if d.extraction_status == "success"}
    if not extracted_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No documents have been extracted yet. Run extraction first."
        )

    try:
        run = verification_service.run_all_checks(db, bundle)

        checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == run.run_id).all()
        disc = db.query(Discrepancy).filter(Discrepancy.run_id == run.run_id).all()

        critical_count = sum(1 for d in disc if d.severity == "critical")
        high_count = sum(1 for d in disc if d.severity == "high")
        risk_score = float(run.overall_risk_score or 0.0)

        return VerificationTriggerResponse(
            bundle_id=str(bundle.bundle_id),
            run_id=str(run.run_id),
            overall_status=run.overall_status,
            overall_risk_score=risk_score,
            total_checks=len(checks),
            total_discrepancies=len(disc),
            critical_count=critical_count,
            high_count=high_count,
            needs_investigation=risk_score >= 20 or any(d.severity in ("critical", "high") for d in disc),
            message=_status_message(run.overall_status, risk_score, len(disc))
        )

    except Exception as exc:
        logger.exception(f"Verification error for bundle {bundle_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/bundle/{bundle_id}/latest", response_model=VerificationRunOut)
def get_latest_run(
    bundle_id: str,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """Return the most recent verification run for an authorized bundle."""
    run = (
        db.query(VerificationRun)
        .filter(VerificationRun.bundle_id == bundle.bundle_id)
        .order_by(VerificationRun.started_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="No verification run found for this bundle")
    return _enrich_run(db, run)


@router.get("/bundle/{bundle_id}/all", response_model=List[VerificationRunOut])
def get_all_runs(
    bundle_id: str,
    bundle: AuditBundle = Depends(verify_bundle_access),
    db: Session = Depends(get_db)
):
    """Return all verification runs for an authorized bundle (audit trail)."""
    runs = (
        db.query(VerificationRun)
        .filter(VerificationRun.bundle_id == bundle.bundle_id)
        .order_by(VerificationRun.started_at.desc())
        .all()
    )
    return [_enrich_run(db, r) for r in runs]


@router.get("/{run_id}", response_model=VerificationRunOut)
def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return a specific verification run by run_id, verifying bundle access."""
    run = db.query(VerificationRun).filter(VerificationRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Verification run not found")

    # Authorize bundle access
    verify_bundle_access(run.bundle_id, current_user, db)

    return _enrich_run(db, run)


# ── helpers ────────────────────────────────────────────────────────────────────

def _enrich_run(db: Session, run: VerificationRun) -> VerificationRunOut:
    """Attach checks and discrepancies to ORM run before serializing."""
    checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == run.run_id).all()
    disc = db.query(Discrepancy).filter(Discrepancy.run_id == run.run_id).all()

    run_dict = {
        "run_id": run.run_id,
        "bundle_id": run.bundle_id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "overall_status": run.overall_status,
        "overall_risk_score": run.overall_risk_score,
        "rules_version": run.rules_version,
        "checks": checks,
        "discrepancies": disc
    }
    return VerificationRunOut(**{k: v for k, v in run_dict.items()})


def _status_message(status: str, risk_score: float, disc_count: int) -> str:
    if status == "clean":
        return "✅ 4-Way Match PASSED — All checks passed. Bundle is clean."
    elif status == "flagged":
        return f"⚠️  Bundle flagged — {disc_count} discrepancy(ies) detected. Risk score: {risk_score:.0f}/100."
    elif status == "critical":
        return f"🚨 CRITICAL — {disc_count} issue(s) detected. Risk score: {risk_score:.0f}/100. Do not approve payment."
    elif status == "incomplete":
        return "❌ Incomplete — One or more required documents are missing. Cannot complete 4-way match."
    return "Verification complete."
