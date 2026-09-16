from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.deps import get_current_user, verify_bundle_access
from app.models import User
from app.schemas.router_schemas import RouterDecision, RouterClassifyRequest
from app.agents.router_agent import router_service

router = APIRouter(prefix="/router", tags=["router"])

@router.post("/classify", response_model=RouterDecision)
def classify_user_query(
    req: RouterClassifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    POST /api/v1/router/classify
    Analyzes natural language user queries using the LLM Router Agent.
    Returns structured JSON decision including user_intent, target_workflow, txn_reference, and clarification flags.
    """
    if req.bundle_id:
        verify_bundle_access(req.bundle_id, current_user, db)

    decision = router_service.classify_query(
        user_query=req.user_query,
        bundle_id=req.bundle_id
    )
    return decision
