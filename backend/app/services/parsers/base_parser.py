"""
base_parser.py
--------------
Abstract base class for all document parsers.

Every parser (LLM-based or deterministic) must:
  1. Accept a pdf_path and raw_text
  2. Return an ExtractionResult dataclass
  3. Never raise unhandled exceptions — all errors go into ExtractionResult

The ExtractionService uses this interface uniformly.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExtractionResult:
    """
    Uniform output produced by every DocumentParser.
    Stored verbatim into AgentExecutionLog.output_snapshot for debugging.
    """
    # Core extraction output
    extracted_obj: Optional[Any] = None        # Validated Pydantic model or None on failure
    success: bool = False

    # Text pipeline
    raw_text: str = ""                          # Original text from PyMuPDF
    cleaned_text: str = ""                      # After preprocessing

    # LLM interaction (None for deterministic parsers)
    prompt: Optional[str] = None
    raw_llm_response: Optional[str] = None

    # Validation
    parsed_json: Optional[Dict[str, Any]] = None
    validation_errors: List[str] = field(default_factory=list)
    numeric_validation_passed: bool = False

    # Retry
    retry_attempted: bool = False
    retry_response: Optional[str] = None

    # Quality
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)

    # Metadata
    model_used: str = "unknown"
    tokens_used: int = 0
    latency_ms: int = 0

    def to_log_snapshot(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for AgentExecutionLog.output_snapshot."""
        return {
            "success": self.success,
            "cleaned_text": self.cleaned_text,
            "prompt": self.prompt,
            "raw_llm_response": self.raw_llm_response,
            "parsed_json": self.parsed_json,
            "validation_errors": self.validation_errors,
            "numeric_validation_passed": self.numeric_validation_passed,
            "retry_attempted": self.retry_attempted,
            "retry_response": self.retry_response,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "extracted_data": self.extracted_obj.model_dump() if self.extracted_obj else None,
        }


class BaseDocumentParser(ABC):
    """
    Abstract base class for all document parsers.

    Subclasses must implement `extract()`.
    The `_timed_extract()` helper wraps it with latency tracking.
    """

    @abstractmethod
    def extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        """
        Parse a document and return an ExtractionResult.

        Args:
            pdf_path: Absolute path to the PDF file
            raw_text: Raw text already extracted from the PDF
                      (stored in Document.raw_text). Pre-extracted
                      to avoid re-reading the file on retry.

        Returns:
            ExtractionResult — always returns, never raises.
        """
        ...

    def timed_extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        """Wraps extract() with latency measurement."""
        start = time.time()
        result = self.extract(pdf_path, raw_text)
        result.latency_ms = int((time.time() - start) * 1000)
        return result
