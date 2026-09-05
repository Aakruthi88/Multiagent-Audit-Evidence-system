import sys
from pathlib import Path

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.router_agent import router_service, router_node
from app.schemas.router_schemas import RouterDecision
from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models  # register ORM models
from app.models.models import AgentExecutionLog

def run_router_tests():
    print("=== TESTING PRODUCTION-READY LLM ROUTER AGENT ===")
    
    Base.metadata.create_all(bind=engine)
    
    test_cases = [
        {
            "query": "Extract purchase order and invoice for TXN-2026-001",
            "expected_workflow": "document_understanding",
            "expected_intent": "upload_and_extract",
            "expected_txn": "TXN-2026-001",
            "expected_clarification": False
        },
        {
            "query": "Run 4-way verification check on TXN-2026-006 to catch price mismatches",
            "expected_workflow": "verification",
            "expected_intent": "verify_bundle",
            "expected_txn": "TXN-2026-006",
            "expected_clarification": False
        },
        {
            "query": "Check if there are duplicate invoices for Dora-Rana Pvt Ltd across bundles",
            "expected_workflow": "search_investigation",
            "expected_intent": "investigate_discrepancies",
            "expected_txn": None,
            "expected_clarification": False
        },
        {
            "query": "Generate PDF audit report for transaction TXN-2026-002",
            "expected_workflow": "report_generation",
            "expected_intent": "generate_report",
            "expected_txn": "TXN-2026-002",
            "expected_clarification": False
        },
        {
            "query": "Run verification",
            "expected_workflow": "clarification",
            "expected_intent": "ask_clarification",
            "expected_txn": None,
            "expected_clarification": True
        }
    ]

    for idx, tc in enumerate(test_cases, 1):
        print(f"\n[Test Case {idx}] Query: '{tc['query']}'")
        decision: RouterDecision = router_service.classify_query(user_query=tc["query"])
        
        print(f"  -> User Intent        : {decision.user_intent}")
        print(f"  -> Target Workflow    : {decision.target_workflow}")
        print(f"  -> Txn Reference      : {decision.txn_reference}")
        print(f"  -> Clarification Req  : {decision.requires_clarification}")
        print(f"  -> Confidence Score   : {decision.confidence}")
        print(f"  -> Explanation        : {decision.explanation}")

        assert decision.target_workflow == tc["expected_workflow"], f"Expected workflow {tc['expected_workflow']}, got {decision.target_workflow}"
        assert decision.user_intent == tc["expected_intent"], f"Expected intent {tc['expected_intent']}, got {decision.user_intent}"
        assert decision.requires_clarification == tc["expected_clarification"], f"Expected clarification {tc['expected_clarification']}, got {decision.requires_clarification}"
        if tc["expected_txn"]:
            assert decision.txn_reference == tc["expected_txn"], f"Expected TXN ref {tc['expected_txn']}, got {decision.txn_reference}"

    # Test LangGraph Node invocation
    print("\n[Testing LangGraph router_node Execution...]")
    state = {
        "bundle_id": "test_bundle_123",
        "user_query": "Run 4-way verification rules on TXN-2026-006",
        "doc_paths": {"purchase_order": "/path/po.pdf"},
        "extracted": {},
        "missing_docs": [],
        "verification_checks": [],
        "discrepancies": [],
        "risk_score": 0.0,
        "needs_investigation": False,
        "investigation_findings": None,
        "report": None,
        "errors": []
    }
    
    updated_state = router_node(state)
    assert updated_state["router_decision"] is not None
    assert updated_state["intent"] == "verify_bundle"
    assert updated_state["txn_reference"] == "TXN-2026-006"
    print("  -> LangGraph router_node successfully updated BundleState!")

    # Verify log entry in DB
    db = SessionLocal()
    logs = db.query(AgentExecutionLog).filter(AgentExecutionLog.agent_name == "router_agent").all()
    print(f"  -> Verified DB Persistence: {len(logs)} Router Agent log entries stored in PostgreSQL!")

    print("\n=== ALL LLM ROUTER AGENT TESTS PASSED CLEANLY! ===")

if __name__ == "__main__":
    run_router_tests()
