"""
Verification Agent — LangGraph Node
Wraps the deterministic VerificationService and persists its results to state.
The LLM is NEVER called from this node.
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.agents.state import BundleState
from app.services.verification_service import verification_service
from app.models.models import AuditBundle
from app.core.logging import logger


def verification_node(state: BundleState) -> Dict[str, Any]:
    """
    LangGraph node that:
    1. Pulls the AuditBundle from DB.
    2. Runs all deterministic 4-way match checks.
    3. Returns state updates: verification_checks, discrepancies, risk_score, needs_investigation.
    """
    bundle_id = state["bundle_id"]
    logger.info(f"[Verification Agent] Starting for bundle {bundle_id}")

    db: Session = SessionLocal()
    try:
        bundle = db.query(AuditBundle).filter(
            AuditBundle.bundle_id == bundle_id
        ).first()

        if not bundle:
            return {"errors": [f"Bundle {bundle_id} not found — cannot run verification."]}

        # Update bundle status
        bundle.status = "verifying"
        db.add(bundle)
        db.commit()

        # Run all deterministic checks
        run = verification_service.run_all_checks(db, bundle)

        # Refresh to get populated relationships
        db.refresh(run)

        # Build state-compatible output
        checks_output = []
        discrepancies_output = []

        for check in db.query(
            __import__('app.models.models', fromlist=['VerificationCheck']).VerificationCheck
        ).filter_by(run_id=run.run_id).all():
            checks_output.append({
                "check_id": str(check.check_id),
                "check_type": check.check_type,
                "status": check.status,
                "expected": check.expected_value,
                "actual": check.actual_value,
                "variance": str(check.variance) if check.variance else None,
                "severity": check.severity,
                "explanation": check.explanation
            })

        for disc in db.query(
            __import__('app.models.models', fromlist=['Discrepancy']).Discrepancy
        ).filter_by(run_id=run.run_id).all():
            discrepancies_output.append({
                "discrepancy_id": str(disc.discrepancy_id),
                "category": disc.category,
                "severity": disc.severity,
                "description": disc.description,
                "recommended_action": disc.recommended_action
            })

        risk_score = float(run.overall_risk_score or 0.0)
        overall_status = run.overall_status

        # Mark bundle status based on results
        if overall_status == "clean":
            bundle.status = "verified"
        elif overall_status in ("flagged", "critical"):
            bundle.status = "flagged"
        elif overall_status == "incomplete":
            bundle.status = "incomplete"
        else:
            bundle.status = "verified"
        db.add(bundle)
        db.commit()

        logger.info(
            f"[Verification Agent] Done — status={overall_status}, "
            f"risk={risk_score}, checks={len(checks_output)}, discrepancies={len(discrepancies_output)}"
        )

        return {
            "verification_run_id": str(run.run_id),
            "verification_checks": checks_output,
            "discrepancies": discrepancies_output,
            "risk_score": risk_score,
            "needs_investigation": risk_score >= 20 or any(
                d["severity"] in ("critical", "high") for d in discrepancies_output
            ),
        }

    except Exception as exc:
        logger.exception(f"[Verification Agent] Error: {exc}")
        return {"errors": [f"Verification failed: {str(exc)}"]}
    finally:
        db.close()
