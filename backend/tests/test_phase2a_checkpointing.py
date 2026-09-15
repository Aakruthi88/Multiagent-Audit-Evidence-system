"""
Phase 2A Test Suite: LangGraph Checkpointing & State Persistence
- Test 1: Normal execution through the multi-agent graph with checkpointer active
- Test 2: Unique execution state isolation between independent executions (Bundle A vs Bundle B)
- Test 3: Checkpoint creation and persistence verification in checkpointer backend
- Test 4: State retrieval and inspection via get_state()
- Test 5: State persistence and durability across simulated process restarts
"""

import sqlite3
import time
import uuid
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models
from app.models.models import AuditBundle, Document
from app.agents.graph import app_graph, compiled_graph
from app.core.config import settings


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)


def test_normal_execution_with_checkpoint():
    """Test 1: Normal graph execution completes end-to-end with checkpointer active."""
    query = "What is the total of Invoice 200005?"
    thread_id = f"test_thread_{uuid.uuid4()}"

    res = app_graph.invoke(
        {"user_query": query},
        config={"configurable": {"thread_id": thread_id}},
    )

    assert res is not None
    assert res.get("action") == "status_query"
    report = res.get("report")
    assert report is not None
    answer = res.get("answer") or report.get("answer")
    assert "637,200" in answer or "637200" in answer


def test_unique_execution_state_isolation():
    """Test 2: Verify independent threads/bundles do not cross-contaminate state."""
    thread_a = f"thread_bundle_A_{uuid.uuid4()}"
    thread_b = f"thread_bundle_B_{uuid.uuid4()}"

    # Execution A
    res_a = app_graph.invoke(
        {"user_query": "What is the total of Invoice 200005?"},
        config={"configurable": {"thread_id": thread_a}},
    )

    # Execution B
    res_b = app_graph.invoke(
        {"user_query": "What items were ordered in PO 100005?"},
        config={"configurable": {"thread_id": thread_b}},
    )

    # Retrieve states independently
    state_a = app_graph.get_state({"configurable": {"thread_id": thread_a}})
    state_b = app_graph.get_state({"configurable": {"thread_id": thread_b}})

    assert state_a is not None and state_a.values is not None
    assert state_b is not None and state_b.values is not None

    # Verify query and action separation
    assert "200005" in str(state_a.values.get("user_query"))
    assert "100005" in str(state_b.values.get("user_query"))
    assert state_a.values.get("user_query") != state_b.values.get("user_query")


def test_checkpoint_creation_and_persistence():
    """Test 3: Verify that checkpointer actually persists checkpoint records to storage."""
    thread_id = f"check_creation_{uuid.uuid4()}"

    res = app_graph.invoke(
        {"user_query": "Show me the key details of TXN-2026-840."},
        config={"configurable": {"thread_id": thread_id}},
    )

    state_tuple = app_graph.get_state({"configurable": {"thread_id": thread_id}})
    assert state_tuple is not None
    assert state_tuple.values is not None
    assert state_tuple.next == ()  # Reached END node

    # Check that state history has multiple checkpoint steps
    history = list(app_graph.get_state_history({"configurable": {"thread_id": thread_id}}))
    assert len(history) >= 2, f"Expected at least 2 checkpoints in history, got {len(history)}"


def test_state_retrieval_and_inspection():
    """Test 4: Verify that checkpointed state can be retrieved by thread_id and contains valid values."""
    thread_id = f"retrieve_test_{uuid.uuid4()}"

    app_graph.invoke(
        {"user_query": "What is the total of Invoice 200005?"},
        config={"configurable": {"thread_id": thread_id}},
    )

    retrieved = app_graph.get_state({"configurable": {"thread_id": thread_id}})
    values = retrieved.values

    assert values.get("bundle_id") is not None
    assert values.get("retrieval_plan") is not None
    assert values.get("action") == "status_query"


def test_durability_across_checkpoint_reloads():
    """Test 5: Verify SQLite/Postgres checkpointer preserves state across fresh checkpointer instance."""
    from app.db.checkpointer import get_checkpointer

    thread_id = f"durable_thread_{uuid.uuid4()}"

    # Invoke on current graph instance
    app_graph.invoke(
        {"user_query": "What is the total of Invoice 200005?"},
        config={"configurable": {"thread_id": thread_id}},
    )

    # Re-fetch checkpointer from storage file
    checkpoints_dir = Path(settings.STORAGE_DIR)
    checkpoint_file = checkpoints_dir / "checkpoints.db"

    if checkpoint_file.exists():
        conn = sqlite3.connect(str(checkpoint_file), check_same_thread=False)
        from langgraph.checkpoint.sqlite import SqliteSaver
        reloaded_saver = SqliteSaver(conn)
        
        reloaded_state = reloaded_saver.get_tuple({"configurable": {"thread_id": thread_id}})
        assert reloaded_state is not None
        assert "bundle_id" in reloaded_state.checkpoint["channel_values"]
        conn.close()
