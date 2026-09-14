"""
app/core/gemini_client.py
-------------------------
Shared Google Gemini client provider using the official `google-genai` SDK.
Provides thread-safe access to Gemini models with fallback handling.
Never logs or exposes API keys.
"""

import os
import logging
from typing import Optional, Tuple, Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None

def get_gemini_client():
    """Singleton getter for Google GenAI Client."""
    global _client
    api_key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key.lower() in ("your_gemini_api_key_here", "placeholder", "changeme"):
        return None

    if _client is None:
        try:
            from google import genai
            _client = genai.Client(api_key=api_key)
        except Exception as exc:
            logger.error(f"[GeminiClient] Failed to initialize Google GenAI Client: {exc}")
            return None
    return _client


def call_gemini(
    prompt: str,
    system_instruction: Optional[str] = None,
    response_mime_type: Optional[str] = None
) -> Tuple[Optional[str], str, int, Optional[str]]:
    """Gemini disabled - local Ollama is the sole generation provider."""
    return None, "disabled", 0, "Gemini is completely disabled"
