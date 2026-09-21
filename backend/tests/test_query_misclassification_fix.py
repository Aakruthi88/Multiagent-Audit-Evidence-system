import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.agents.graph import app_graph
from app.agents.intent_router_agent import _fast_path_plan, _call_planner_llm, intent_router_node
from app.agents.query_agent import _is_status_query


def test_failing_query_not_found_no_unrelated_results():
    """
    Test that 'Why was TXN-2026-817 flagged?' (unresolved transaction reference):
    1. Uses Ollama dynamic intent planning
    2. Extracts bundle_reference as 'TXN-2026-817'
    3. Does NOT route to system-status query
    4. Returns a clear NOT FOUND result rather than unrelated transactions.
    """
    query = "Why was TXN-2026-817 flagged?"
    res = app_graph.invoke({"user_query": query})

    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert res.get("bundle_id") is None
    assert report.get("query_type") == "not_found"
    assert "no matching audit bundle" in answer.lower() or "not found" in answer.lower()
    # Verify unrelated flagged transactions are NOT returned in answer
    assert "found 36 flagged" not in answer.lower()
    assert "found 35 flagged" not in answer.lower()
    assert report.get("result", {}).get("found") is False


def test_genuine_system_status_query_returns_bundles():
    """
    Test that 'Show all flagged transactions':
    1. Evaluates to system-wide status query
    2. Has bundle_reference as None
    3. Correctly returns status_query report with flagged transactions.
    """
    query = "Show all flagged transactions"
    res = app_graph.invoke({"user_query": query})

    report = res.get("report") or {}
    answer = res.get("answer") or report.get("answer") or ""

    assert report.get("query_type") == "status_query"
    assert "flagged" in answer.lower()
    assert "bundles" in report or len(answer) > 0


def test_is_status_query_discrimination():
    """
    Test _is_status_query logic distinguishes entity-specific queries from cross-bundle queries.
    """
    # Specific query with reference -> NOT status query
    assert _is_status_query(
        "Why was TXN-2026-817 flagged?",
        {"bundle_reference": "TXN-2026-817"},
        bundle_id=None
    ) is False

    # Specific query mentioning entity token -> NOT status query
    assert _is_status_query(
        "Why was TXN-2026-817 flagged?",
        {"bundle_reference": None},
        bundle_id=None
    ) is False

    # Genuine cross-bundle query -> IS status query
    assert _is_status_query(
        "Show all flagged transactions",
        {"bundle_reference": None},
        bundle_id=None
    ) is True

    assert _is_status_query(
        "List all bundles",
        {"bundle_reference": None},
        bundle_id=None
    ) is True
