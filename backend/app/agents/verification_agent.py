"""
Verification Agent â€” LangGraph Node (Extended Day 2)
-----------------------------------------------------
Wraps the deterministic VerificationService.
After deterministic checks complete, runs ONE optional LLM call
for borderline checks (vendor_match gray zone 70-85%, partial qty delivery).

The LLM NEVER invents numbers.  It only adjudicates status for cases where
deterministic rules produce a "maybe" â€” borderline fuzzy vendor scores and
partial delivery quantities.  All numbers in the report come from Python.
"""

import json
import re
import time
import uuid as _uuid_lib
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import AgentExecutionLog, AuditBundle, Document
from app.services.verification_service import verification_service


# â”€â”€ LLM judgment schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class LLMVerificationJudgment(BaseModel):
    check_name: str
    status: str   # "pass" | "fail" | "warning"
    confidence: float
    explanation: str


# â”€â”€ Borderline detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_VENDOR_GRAY_ZONE = (15.0, 30.0)  # variance range: 15â€“30 = score 70â€“85%


def _is_borderline(check: Dict[str, Any]) -> bool:
    """Return True if a check is in a gray zone that warrants LLM adjudication."""
    check_type = check.get("check_type", "")

    # Vendor match gray zone
    if "vendor_match" in check_type or "vendor" in check_type:
        variance = check.get("variance")
        if variance is not None:
            try:
                v = float(variance)
                if _VENDOR_GRAY_ZONE[0] <= v <= _VENDOR_GRAY_ZONE[1]:
                    return True
            except (TypeError, ValueError):
                pass

    # Quantity partial delivery warning
    if "qty" in check_type and check.get("status") == "warning":
        return True

    return False


# â”€â”€ LLM adjudication call â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ADJUDICATION_SYSTEM = """You are an audit verification assistant.
You will receive a list of borderline audit check results that could not be
definitively resolved by deterministic rules.
For each check, return your judgment as a JSON array of objects with fields:
  check_name, status ("pass"|"fail"|"warning"), confidence (0.0-1.0), explanation.
Return ONLY valid JSON array â€” no markdown, no extra text."""


def _llm_adjudicate(borderline_checks: List[Dict[str, Any]]) -> List[LLMVerificationJudgment]:
    """Call LLM once with all borderline checks. Returns list of judgments."""
    if not borderline_checks:
        return []

    prompt_data = json.dumps(
        [
            {
                "check_name": c.get("check_type"),
                "status": c.get("status"),
                "expected": c.get("expected"),
                "actual": c.get("actual"),
                "variance": str(c.get("variance", "")),
                "explanation": c.get("explanation"),
            }
            for c in borderline_checks
        ],
        indent=2,
    )
    user_msg = f"Borderline checks to adjudicate:\n{prompt_data}"

    def _parse_judgments(raw: str) -> List[LLMVerificationJudgment]:
        text = re.sub(r"```(?:json)?", "", raw, flags=re.I).strip()
        try:
            items = json.loads(text)
            return [LLMVerificationJudgment.model_validate(i) for i in items]
        except Exception:
            return []

    # Try Ollama (local llama2:latest)
    if settings.OLLAMA_HOST:
        try:
            payload = {
                "model": settings.OLLAMA_MODEL or "llama2:latest",
                "prompt": f"{_ADJUDICATION_SYSTEM}\n\n{user_msg}",
                "format": "json",
                "stream": False,
            }
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
                if res.status_code == 200:
                    judgments = _parse_judgments(res.json().get("response", "[]"))
                    if judgments:
                        return judgments
        except Exception as exc:
            logger.warning(f"[VerificationAgent] Ollama adjudication error: {exc}")

    logger.info("[VerificationAgent] LLM adjudication unavailable â€” keeping deterministic results.")
    return []


# â”€â”€ Verdict aggregation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _compute_verdict(checks_output: List[Dict[str, Any]], discrepancies_output: List[Dict[str, Any]]):
    """
    Returns (verdict, severity):
    - Any critical severity fail   â†’ verdict="anomaly", severity="critical"
    - Only warnings/medium/high    â†’ verdict="anomaly", severity="warning"
    - All pass / not_applicable    â†’ verdict="clean",   severity=None
    """
    severities = [d.get("severity") for d in discrepancies_output]
    if "critical" in severities:
        return "anomaly", "critical"
    if any(s in severities for s in ("high", "medium", "low")):
        return "anomaly", "warning"
    fail_checks = [c for c in checks_output if c.get("status") == "fail"]
    if fail_checks:
        return "anomaly", "warning"
    return "clean", None


# â”€â”€ LangGraph node â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def verification_node(state: BundleState) -> Dict[str, Any]:
    """
    LangGraph node:
    1. Pull AuditBundle from DB.
    2. Run all deterministic 4-way match checks (VerificationService).
    3. Identify borderline checks â†’ run ONE LLM call for adjudication.
    4. Compute extraction_confidence as min across bundle's documents.
    5. Set verdict and severity in state.
    6. Log to agent_execution_log.
    """
    bundle_id = state.get("bundle_id")
    start = time.time()

    # BUG A guard: reject invalid bundle_id before it reaches SQL
    if not bundle_id or not isinstance(bundle_id, str) or not bundle_id.strip():
        logger.error(f"[Verification Agent] Invalid or missing bundle_id: {bundle_id!r} — aborting verification")
        return {
            "errors": ["No valid bundle_id — cannot run verification. Please provide a valid bundle or transaction reference."],
            "verification_checks": [],
            "discrepancies": [],
            "verdict": "error",
            "severity": "critical",
            "risk_score": 0.0,
        }

    logger.info(f"[Verification Agent] Starting for bundle {bundle_id}")
    db: Session = SessionLocal()
    try:
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        if not bundle:
            return {"errors": [f"Bundle {bundle_id} not found â€” cannot run verification."]}

        # â”€â”€ Step 1: Update bundle status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        bundle.status = "verifying"
        db.add(bundle)
        db.commit()

        # â”€â”€ Step 2: Run deterministic checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        run = verification_service.run_all_checks(db, bundle)
        db.refresh(run)

        # Collect check and discrepancy dicts
        VerificationCheck = __import__(
            "app.models.models", fromlist=["VerificationCheck"]
        ).VerificationCheck
        Discrepancy = __import__(
            "app.models.models", fromlist=["Discrepancy"]
        ).Discrepancy

        checks_output: List[Dict[str, Any]] = []
        discrepancies_output: List[Dict[str, Any]] = []

        for check in db.query(VerificationCheck).filter_by(run_id=run.run_id).all():
            checks_output.append(
                {
                    "check_id": str(check.check_id),
                    "check_type": check.check_type,
                    "status": check.status,
                    "expected": check.expected_value,
                    "actual": check.actual_value,
                    "variance": str(check.variance) if check.variance else None,
                    "severity": check.severity,
                    "explanation": check.explanation,
                }
            )

        for disc in db.query(Discrepancy).filter_by(run_id=run.run_id).all():
            discrepancies_output.append(
                {
                    "discrepancy_id": str(disc.discrepancy_id),
                    "category": disc.category,
                    "severity": disc.severity,
                    "description": disc.description,
                    "recommended_action": disc.recommended_action,
                }
            )

        # â”€â”€ Step 3: LLM hybrid adjudication for borderline checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        borderline = [c for c in checks_output if _is_borderline(c)]
        llm_judgments: List[LLMVerificationJudgment] = []
        if borderline:
            logger.info(
                f"[Verification Agent] {len(borderline)} borderline check(s) found â€” calling LLM adjudication."
            )
            llm_judgments = _llm_adjudicate(borderline)

        # Merge LLM judgments back (enrich state output, not DB)
        llm_map = {j.check_name: j for j in llm_judgments}
        for check in checks_output:
            ct = check.get("check_type", "")
            if ct in llm_map:
                j = llm_map[ct]
                check["llm_status"] = j.status
                check["llm_confidence"] = j.confidence
                check["llm_explanation"] = j.explanation

        # â”€â”€ Step 4: Extraction confidence (min across bundle docs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        docs = db.query(Document).filter(Document.bundle_id == bundle_id).all()
        confidences = [
            d.extraction_confidence
            for d in docs
            if d.extraction_confidence is not None
        ]
        extraction_confidence = min(confidences) if confidences else 0.5

        # â”€â”€ Step 5: Verdict and severity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        verdict, severity = _compute_verdict(checks_output, discrepancies_output)

        # Update bundle status based on run outcome
        overall_status = run.overall_status
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

        # â”€â”€ Step 6: Log execution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        latency_ms = int((time.time() - start) * 1000)
        risk_score = float(run.overall_risk_score or 0.0)

        db.add(
            AgentExecutionLog(
                bundle_id=bundle_id,
                agent_name="verification_agent",
                input_snapshot={"bundle_id": bundle_id, "run_id": str(run.run_id)},
                output_snapshot={
                    "overall_status": overall_status,
                    "verdict": verdict,
                    "severity": severity,
                    "risk_score": risk_score,
                    "checks_count": len(checks_output),
                    "discrepancies_count": len(discrepancies_output),
                    "borderline_adjudicated": len(llm_judgments),
                },
                latency_ms=latency_ms,
                status="success",
            )
        )
        db.commit()

        logger.info(
            f"[Verification Agent] Done â€” verdict={verdict}, severity={severity}, "
            f"status={overall_status}, risk={risk_score:.1f}, "
            f"checks={len(checks_output)}, discrepancies={len(discrepancies_output)}"
        )

        return {
            "verification_run_id": str(run.run_id),
            "verification_checks": checks_output,
            "discrepancies": discrepancies_output,
            "risk_score": risk_score,
            "needs_investigation": risk_score >= 20
            or any(d["severity"] in ("critical", "high") for d in discrepancies_output),
            "verdict": verdict,
            "severity": severity,
            "extraction_confidence": extraction_confidence,
        }

    except Exception as exc:
        logger.exception(f"[Verification Agent] Error: {exc}")
        return {"errors": [f"Verification failed: {str(exc)}"]}
    finally:
        db.close()

