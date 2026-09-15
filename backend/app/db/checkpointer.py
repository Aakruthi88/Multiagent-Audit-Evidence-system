import sqlite3
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger

_checkpointer_instance = None


def get_checkpointer() -> Any:
    """
    Returns a persistent, durable LangGraph checkpointer instance configured for the environment:
    - PostgreSQL: When DATABASE_URL points to PostgreSQL, initializes PostgresSaver
      via connection pooling and ensures checkpoint tables are initialized with .setup().
    - SQLite: When DATABASE_URL points to SQLite (or local dev), initializes SqliteSaver
      using storage/checkpoints.db with automatic table initialization via .setup().
    - Fallback: In-memory MemorySaver if filesystem/database initialization fails.
    """
    global _checkpointer_instance
    if _checkpointer_instance is not None:
        return _checkpointer_instance

    db_url = settings.DATABASE_URL or ""

    # 1. PostgreSQL Checkpointer
    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        try:
            import psycopg_pool
            from langgraph.checkpoint.postgres import PostgresSaver

            clean_url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
            pool = psycopg_pool.ConnectionPool(clean_url, max_size=10, kwargs={"autocommit": True})
            saver = PostgresSaver(pool)
            saver.setup()
            logger.info("[checkpointer] Initialized durable PostgreSQL checkpointer (PostgresSaver)")
            _checkpointer_instance = saver
            return saver
        except Exception as exc:
            logger.warning(f"[checkpointer] PostgreSQL checkpointer initialization failed: {exc}. Falling back to SQLite.")

    # 2. SQLite Persistent File Checkpointer
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        storage_path = Path(settings.STORAGE_DIR)
        storage_path.mkdir(parents=True, exist_ok=True)
        checkpoint_file = storage_path / "checkpoints.db"
        conn = sqlite3.connect(str(checkpoint_file), check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        logger.info(f"[checkpointer] Initialized durable SQLite checkpointer (SqliteSaver) at {checkpoint_file}")
        _checkpointer_instance = saver
        return saver
    except Exception as exc:
        logger.warning(f"[checkpointer] SQLite checkpointer initialization failed: {exc}. Falling back to MemorySaver.")

    # 3. In-memory fallback
    from langgraph.checkpoint.memory import MemorySaver

    logger.info("[checkpointer] Using in-memory MemorySaver fallback")
    _checkpointer_instance = MemorySaver()
    return _checkpointer_instance
