"""
text_utils.py
-------------
Shared PDF text extraction and preprocessing utilities.

Used by all document parsers to produce clean, normalized text
before handing it to an LLM or a deterministic parser.
"""

import re
from datetime import datetime, date
import fitz          # PyMuPDF
import pdfplumber
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PDF Text Extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str) -> str:
    """
    Extract raw text from a PDF using PyMuPDF (primary) with pdfplumber fallback.
    Returns the concatenated page text.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    raw_text = ""

    # Primary: PyMuPDF — preserves layout better for structured docs
    try:
        doc = fitz.open(pdf_path)
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text and text.strip():
                pages.append(text.strip())
        doc.close()
        raw_text = "\n\n".join(pages)
        logger.debug(f"PyMuPDF extracted {len(raw_text)} chars from {path.name}")
    except Exception as e:
        logger.warning(f"PyMuPDF failed for {pdf_path}: {e}")

    # Fallback: pdfplumber if PyMuPDF yielded < 20 chars
    if len(raw_text.strip()) < 20:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text and text.strip():
                        pages.append(text.strip())
                fallback = "\n\n".join(pages)
                if len(fallback.strip()) > len(raw_text.strip()):
                    raw_text = fallback
                    logger.info(f"pdfplumber fallback used for {path.name}")
        except Exception as e:
            logger.warning(f"pdfplumber failed for {pdf_path}: {e}")

    return raw_text.strip()


# ---------------------------------------------------------------------------
# Text Preprocessing
# ---------------------------------------------------------------------------

def clean_extracted_text(text: str) -> str:
    """
    Normalise raw PDF text for LLM consumption.

    Rules:
    - Collapse multiple blank lines into a single blank line
    - Collapse runs of spaces/tabs into a single space (per line)
    - Preserve line ordering and newlines (important for table rows)
    - Preserve numeric formatting (commas, decimals, currency symbols)
    - Preserve identifiers (PO numbers, invoice numbers, references)
    - Remove form-feed / carriage-return control characters
    """
    if not text:
        return ""

    # Strip carriage returns & form-feeds
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")

    lines = text.split("\n")
    cleaned_lines: List[str] = []
    prev_blank = False

    for line in lines:
        # Collapse intra-line whitespace (spaces/tabs) but keep leading indent
        # so table columns stay aligned
        stripped = re.sub(r'[ \t]+', ' ', line).rstrip()

        is_blank = not stripped.strip()

        if is_blank:
            if not prev_blank:
                cleaned_lines.append("")   # keep one blank separator
            prev_blank = True
        else:
            cleaned_lines.append(stripped)
            prev_blank = False

    return "\n".join(cleaned_lines).strip()


def remove_page_headers_footers(text: str, min_repeat: int = 2) -> str:
    """
    Heuristically remove page headers and footers.

    Strategy: lines that appear identically at the top/bottom of every page
    (separated by double newlines) are likely headers/footers.
    Only removes lines shorter than 80 chars that repeat >= min_repeat times.
    """
    pages = text.split("\n\n")
    if len(pages) < 2:
        return text

    # Collect candidate lines (short, appearing on multiple pages)
    line_counts: dict = {}
    for page in pages:
        page_lines = [l.strip() for l in page.split("\n") if l.strip()]
        if not page_lines:
            continue
        # Check first 2 and last 2 lines of each page
        candidates = page_lines[:2] + page_lines[-2:]
        for c in candidates:
            if len(c) < 80:
                line_counts[c] = line_counts.get(c, 0) + 1

    repeated = {line for line, count in line_counts.items() if count >= min_repeat}

    if not repeated:
        return text

    output_lines = []
    for line in text.split("\n"):
        if line.strip() in repeated:
            continue
        output_lines.append(line)

    return "\n".join(output_lines).strip()


def normalize_whitespace_in_table(text: str) -> str:
    """
    Collapse excessive whitespace between columns while keeping newlines intact.
    Useful for tab-separated or multi-space-separated table rows.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        # Collapse multiple spaces to 2 spaces (acts like column separator)
        collapsed = re.sub(r' {3,}', '  ', line)
        result.append(collapsed)
    return "\n".join(result)


def preprocess_for_llm(text: str) -> str:
    """
    Full preprocessing pipeline for LLM submission:
    1. clean_extracted_text
    2. remove_page_headers_footers
    3. normalize_whitespace_in_table
    """
    text = clean_extracted_text(text)
    text = remove_page_headers_footers(text)
    text = normalize_whitespace_in_table(text)
    return text


# ---------------------------------------------------------------------------
# Shared Field / Numeric / Date Parsing Utilities (DRY)
# ---------------------------------------------------------------------------

def clean_float(val: Any) -> Optional[float]:
    """Parse a numeric string or number (with commas) to float. Returns None on failure."""
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def normalize_date(s: Optional[str]) -> Optional[str]:
    """Convert any supported date format to ISO YYYY-MM-DD string. Returns None on failure."""
    if not s or not isinstance(s, str):
        return None
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def parse_date_flexible(date_str: Optional[str]) -> Optional[date]:
    """Robustly parses date strings in YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY formats into datetime.date."""
    if not date_str or not isinstance(date_str, str):
        return None
    cleaned = date_str.strip()

    match = re.search(r'(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})', cleaned)
    if match:
        cleaned = match.group(1)

    formats = [
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y",
        "%Y/%m/%d", "%d.%m.%Y", "%Y.%m.%d"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def log_field_extraction(doc_type: str, field: str, pattern_desc: str, raw_match: Any, parsed: Any, status: str):
    """Emit a structured debug log for a single extracted field."""
    logger.debug(
        f"[{doc_type}] field={field!r:20s}  pattern={pattern_desc!r:30s}  "
        f"raw={str(raw_match)!r:30s}  parsed={str(parsed)!r:20s}  status={status}"
    )

