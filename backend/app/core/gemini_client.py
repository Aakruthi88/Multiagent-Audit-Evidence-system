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

    candidate_models = [primary_model]
    for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.6-flash"]:
        if m not in candidate_models:
            candidate_models.append(m)

    last_error = None
    from google.genai import types

    config_kwargs = {}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if response_mime_type:
        config_kwargs["response_mime_type"] = response_mime_type

    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )

            text = response.text if response and hasattr(response, "text") else None
            usage = getattr(response, "usage_metadata", None)
            tokens = getattr(usage, "total_token_count", 0) if usage else 0

            if text:
                return text.strip(), f"google/{model_name}", tokens, None
            else:
                last_error = f"Empty response from {model_name}"

        except Exception as exc:
            err_str = str(exc)
            last_error = err_str
            # If 404 NOT_FOUND model deprecation/unavailable error, try next candidate model
            if "404" in err_str or "NOT_FOUND" in err_str or "no longer available" in err_str:
                logger.warning(f"[GeminiClient] Model '{model_name}' unavailable (404), trying fallback...")
                continue
            else:
                # Other errors (auth, quota, timeout) fail fast
                logger.error(f"[GeminiClient] API call error ({model_name}): {exc}")
                return None, f"google/{model_name}", 0, err_str

    return None, f"google/{primary_model}", 0, last_error or "All Gemini model candidates failed"
