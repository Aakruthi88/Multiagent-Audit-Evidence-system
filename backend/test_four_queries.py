import time
from app.agents.graph import app_graph

def test_query(q_id: str, query_text: str):
    print("\n" + "=" * 75)
    print(f"[{q_id}] QUERY: {query_text}")
    print("=" * 75)
    state = {
        "user_query": query_text,
        "authenticated_user": {"user_id": "test_admin", "email": "admin@deloitte.com", "role": "admin"}
    }
    t0 = time.time()
    result = app_graph.invoke(state)
    elapsed = time.time() - t0
    report = result.get("report") or {}
    answer = report.get("answer") or result.get("answer")
    timings = result.get("agent_timings") or {}
    
    print(f"⏱️  Overall Pipeline Latency: {elapsed:.2f}s")
    print("📊 Node Timings Breakdown:")
    for node, ms in timings.items():
        print(f"   • {node:<20}: {ms:>8.2f} ms")
    print(f"\n📝 Synthesized Answer:\n{answer}\n")

if __name__ == "__main__":
    test_query("A", "What is the total amount of Invoice 200004?")
    test_query("B", "Verify Invoice 200004 against PO 100004.")
    test_query("C", "Why was Invoice 200004 flagged?")
    test_query("D", "Give me the detailed audit report for Invoice 200004.")
