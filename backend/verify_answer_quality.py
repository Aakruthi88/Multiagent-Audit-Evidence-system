"""
verify_answer_quality.py - Evaluate LLM answer quality, factual grounding, and query latency across 10 queries.
"""
import sys
import time
import json

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

from app.agents.graph import app_graph

QUERIES = [
    {"index": 1, "query": "What is the total of Invoice 200005?"},
    {"index": 2, "query": "Verify invoice 200005 against PO 100005 and GRN-2026-0005"},
    {"index": 3, "query": "Why was TXN-2026-895 flagged?"},
    {"index": 4, "query": "Why was transaction TXN-2026-895 failed?"},
    {"index": 5, "query": "Was the invoice fully paid?"},
    {"index": 6, "query": "Show me all amount mismatches"},
    {"index": 7, "query": "Does the invoice match the GRN?"},
    {"index": 8, "query": "Generate an audit report for invoice 200005"},
    {"index": 9, "query": "What is the total of Invoice 200006?"},
    {"index": 10, "query": "What is the status of Invoice INV-999999?"},
]

def run_tests():
    print("=" * 80, flush=True)
    print("PHASE 5B: ANSWER QUALITY & LATENCY EVALUATION (DIRECT GRAPH)", flush=True)
    print("=" * 80, flush=True)

    results = []

    for item in QUERIES:
        idx = item["index"]
        q = item["query"]
        print(f"\n[{idx}/10] Query: '{q}'", flush=True)

        initial_state = {
            "bundle_id": None,
            "user_query": q,
            "user_id": "00000000-0000-0000-0000-000000000001",
            "user_role": "admin",
            "authorized_bundle_ids": None,
            "action": None,
            "intent": None,
            "router_decision": None,
            "query_filters": None,
            "txn_reference": None,
            "doc_paths": {},
            "extracted": {},
            "missing_docs": [],
            "extraction_confidence": 1.0,
            "retrieval_plan": None,
            "evidence_table": None,
            "vendor_similarity_matches": None,
            "verification_run_id": None,
            "verification_checks": [],
            "discrepancies": [],
            "risk_score": 0.0,
            "needs_investigation": False,
            "verdict": None,
            "severity": None,
            "investigation_findings": None,
            "report": None,
            "errors": [],
        }

        t0 = time.perf_counter()
        final_state = app_graph.invoke(initial_state)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        report = final_state.get("report") or {}
        answer = report.get("answer") or report.get("conclusion") or report.get("narrative") or final_state.get("verdict")
        verdict = final_state.get("verdict")
        plan = final_state.get("retrieval_plan") or {}

        print(f"Latency: {elapsed_ms:.2f} ms | Verdict: {verdict}", flush=True)
        print(f"Intent: {plan.get('intent')} | Req Docs: {plan.get('required_documents')}", flush=True)
        print(f"Answer:\n{answer}\n", flush=True)

        results.append({
            "index": idx,
            "query": q,
            "latency_ms": elapsed_ms,
            "verdict": verdict,
            "intent": plan.get("intent"),
            "required_documents": plan.get("required_documents"),
            "answer": answer
        })

    with open("answer_quality_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80, flush=True)
    print("LATENCY SUMMARY TABLE", flush=True)
    print("=" * 80, flush=True)
    for r in results:
        print(f"Query {r['index']:2d}: {r['latency_ms']:8.2f} ms | {r['query']}", flush=True)

if __name__ == "__main__":
    run_tests()
