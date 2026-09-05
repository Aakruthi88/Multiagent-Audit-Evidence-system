from langgraph.graph import StateGraph, END
from app.agents.state import BundleState
from app.agents.router_agent import router_node
from app.agents.document_agent import document_understanding_node
from app.agents.verification_agent import verification_node

# Initialize graph
workflow = StateGraph(BundleState)

# ── Register Nodes ─────────────────────────────────────────────────────────────
workflow.add_node("router", router_node)
workflow.add_node("document_understanding", document_understanding_node)
workflow.add_node("verification", verification_node)

# Set entry point
workflow.set_entry_point("router")

# ── Routing Functions ──────────────────────────────────────────────────────────

def route_after_router(state: BundleState) -> str:
    """Route after LLM Router Agent decision."""
    decision = state.get("router_decision") or {}

    if decision.get("requires_clarification"):
        return "end"

    target = decision.get("target_workflow", "document_understanding")

    if target == "verify_bundle":
        return "verification"
    elif target == "document_understanding" or state.get("doc_paths"):
        return "document_understanding"

    return "end"


def route_after_extraction(state: BundleState) -> str:
    """After extraction, always proceed to verification."""
    errors = state.get("errors", [])
    if errors:
        return "end"
    return "verification"


# ── Edges ──────────────────────────────────────────────────────────────────────
workflow.add_conditional_edges(
    "router",
    route_after_router,
    {
        "document_understanding": "document_understanding",
        "verification": "verification",
        "end": END
    }
)

workflow.add_conditional_edges(
    "document_understanding",
    route_after_extraction,
    {
        "verification": "verification",
        "end": END
    }
)

workflow.add_edge("verification", END)

# ── Compile ────────────────────────────────────────────────────────────────────
app_graph = workflow.compile()
