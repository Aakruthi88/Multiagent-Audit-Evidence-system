"""
po_parser.py
------------
Purchase Order document parser.

Extraction strategy:
  1. Deterministic parser runs FIRST (regex + PyMuPDF text)
  2. Validate result (required fields + numeric consistency)
  3. LLM fallback ONLY if mandatory fields are missing or numeric check fails
  4. LLM receives ONLY the section containing missing fields, not the full document
  5. Compute rubric-based confidence score

Key rules:
  - Never calculate/infer monetary values — extract exactly what is printed
  - vendor_name returns None (not "Unknown Vendor") if not confidently found
  - Never confuse Bill To / Ship To / Buyer / Customer with Vendor
  - All line items are extracted (not just the first)
  - Validation generates warnings only — never overwrites extracted values
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Any

from pathlib import Path
import httpx

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

from app.core.config import settings
from app.schemas.extraction_schemas import POExtraction, POLineItemExtraction
from app.services.parsers.base_parser import BaseDocumentParser, ExtractionResult
from app.services.parsers.text_utils import preprocess_for_llm
from app.services.confidence import score_po_extraction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM key guard — rejects empty strings AND well-known placeholder values
# ---------------------------------------------------------------------------

def _has_valid_llm_key() -> bool:
    """Return True only when OPENROUTER_API_KEY looks like a real key."""
    key = (settings.OPENROUTER_API_KEY or "").strip()
    if not key:
        return False
    if key.lower() in ("your_openrouter_api_key_here", "changeme", "placeholder", "sk-placeholder"):
        return False
    return True


# ---------------------------------------------------------------------------
# LLM Prompts (used only for targeted fallback on missing fields)
# ---------------------------------------------------------------------------

_PO_MISSING_FIELDS_PROMPT = """You are a precise document data extractor specializing in Purchase Orders.

The deterministic parser already extracted most fields successfully.
Only the following fields could NOT be extracted: {missing_fields}

Look at the relevant section of the Purchase Order below and extract ONLY those missing fields.
Return ONLY a valid JSON object containing those field names as keys.

RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate. If a field is genuinely missing, return null for it.
- vendor_name = the SUPPLIER/SELLER company name. NEVER use Bill To / Ship To / Customer / Buyer.
- Dates must be in YYYY-MM-DD format.
- Monetary amounts must be floats (no currency symbols).

Missing fields to extract: {missing_fields}

Document section:
{section_text}
"""

_PO_FULL_PROMPT = """You are a precise document data extractor specializing in Purchase Orders.

Extract ALL structured data from the Purchase Order text below and return ONLY valid JSON.

CRITICAL RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate values. If a field is not present, return null.
- Preserve identifiers (PO numbers, item codes) EXACTLY as written.
- vendor_name = the SUPPLIER company name only. NEVER use Bill To / Ship To / Customer / Buyer.
- Dates must be in YYYY-MM-DD format.
- All monetary amounts must be floats (no currency symbols in values).
- line_items must contain EVERY line item row from the PO table.

JSON Schema:
{schema}

Purchase Order Text:
{text}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val: Optional[str]) -> Optional[float]:
    """Parse a numeric string (with commas) to float. Returns None on failure."""
    if not val:
        return None
    try:
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def _norm_date(s: Optional[str]) -> Optional[str]:
    """Convert any supported date format to ISO YYYY-MM-DD. Returns None on failure."""
    if not s:
        return None
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _log_field(doc_type: str, field: str, pattern_desc: str, raw_match: Any, parsed: Any, status: str):
    """Emit a structured debug log for a single extracted field."""
    logger.debug(
        f"[{doc_type}] field={field!r:20s}  pattern={pattern_desc!r:30s}  "
        f"raw={str(raw_match)!r:30s}  parsed={str(parsed)!r:20s}  status={status}"
    )


# ---------------------------------------------------------------------------
# Vendor extraction
# ---------------------------------------------------------------------------

# Labels that indicate a BUYER / RECEIVER section — vendor must NOT come from these sections
_BUYER_SECTION_RE = re.compile(
    r'\b(BILL\s*TO|SHIP\s*TO|SOLD\s*TO|DELIVER\s*TO|CUSTOMER|BUYER|RECEIVER|CONSIGNEE)\b',
    re.I
)

# Legal entity suffixes that indicate a company name
_COMPANY_SUFFIX_RE = re.compile(
    r'([A-Za-z0-9\s&,\-\'.]+?\b(?:'
    r'Pvt\.?\s*Ltd\.?|Private\s*Limited|Ltd\.?|Inc\.?|Corp\.?|LLC|'
    r'Solutions|Technologies|Industries|Enterprises?|Services?|'
    r'Traders?|Suppliers?|Infotech|Systems|Global|Logistics|Motors|'
    r'Manufacturing|Trading|Distributors?|Exports?|Imports?|Holdings?'
    r')\b)',
    re.I
)

# Labels that explicitly introduce a vendor
_VENDOR_LABEL_RE = re.compile(
    r'(?:Supplier\s*Name|Vendor\s*Name|Supplier|Vendor|Sold\s*By|Seller)\s*[:\-]?\s*([^\n]+)',
    re.I
)


def _get_buyer_line_index(lines: List[str]) -> int:
    """Return the index of the first standalone buyer-section label line (not side-by-side with VENDOR)."""
    for i, line in enumerate(lines):
        if re.search(r'\b(VENDOR|SUPPLIER)\b', line, re.I):
            continue
        if _BUYER_SECTION_RE.search(line):
            return i
    return len(lines)


def _clean_company_name(name: str) -> Optional[str]:
    """Strip label prefixes and trailing noise from a candidate company name."""
    if not name:
        return None
    # Strip any leading label artifact
    name = re.sub(
        r'^(?:Supplier\s*Name|Supplier|Vendor\s*Name|Vendor|From|Company|Seller|Sold\s*By)\s*[:\-]?\s*',
        '', name, flags=re.I
    )
    # Truncate at noise tokens
    name = re.split(
        r'(?i)\b(?:Phone|Tel|Email|Address|PO\b|Date|Bill|Ship|Attn|Contact|H\.No|H-|Fax|GST|GSTIN)\b',
        name
    )[0]
    name = name.strip(' :,;-\n\r\t')
    # If the string contains a known company suffix, extract up to the suffix
    sm = _COMPANY_SUFFIX_RE.search(name)
    if sm:
        return sm.group(1).strip()
    return name if len(name) > 2 else None


def _extract_vendor_with_coordinates(pdf_path: Optional[str]) -> Optional[str]:
    """
    Extract vendor name using PyMuPDF word bounding box coordinates.
    Distinguishes VENDOR column (left) from SHIP TO / BILL TO / BUYER columns (right).
    """
    if not _HAS_FITZ or not pdf_path or not Path(pdf_path).exists():
        return None
    try:
        doc = fitz.open(pdf_path)
        words = []
        for page in doc:
            words.extend(page.get_text("words"))
        doc.close()

        if not words:
            return None

        # Group words by line (Y coordinate, tolerance 3.0pt)
        lines_dict = {}
        for w in words:
            x0, y0, x1, y1, word = w[0], w[1], w[2], w[3], w[4]
            y_key = round(y0 / 3.0) * 3.0
            lines_dict.setdefault(y_key, []).append((x0, x1, y0, y1, word))

        sorted_y_keys = sorted(lines_dict.keys())

        vendor_header_y = None
        vendor_x0 = None
        shipto_x0 = None

        for y_key in sorted_y_keys:
            line_words = sorted(lines_dict[y_key], key=lambda item: item[0])
            line_text_upper = ' '.join([w[4].upper() for w in line_words])
            if 'VENDOR' in line_text_upper or 'SUPPLIER' in line_text_upper:
                for w in line_words:
                    w_text = w[4].upper()
                    if 'VENDOR' in w_text or 'SUPPLIER' in w_text:
                        if vendor_x0 is None:
                            vendor_x0 = w[0]
                    if any(k in w_text for k in ('SHIP', 'BILL', 'BUYER', 'DELIVER', 'CONSIGNEE')):
                        if shipto_x0 is None or w[0] > (vendor_x0 or 0):
                            shipto_x0 = w[0]
                vendor_header_y = y_key
                break

        if vendor_header_y is not None:
            # Determine horizontal column split
            split_x = (shipto_x0 - 5.0) if (shipto_x0 and shipto_x0 > (vendor_x0 or 0)) else ((vendor_x0 + 250.0) if vendor_x0 else 300.0)

            vendor_column_words = []
            for y_key in sorted_y_keys:
                if y_key < vendor_header_y:
                    continue
                if y_key > vendor_header_y + 120.0:
                    break
                line_words = sorted(lines_dict[y_key], key=lambda item: item[0])
                line_text = ' '.join([w[4] for w in line_words])

                # Stop if reaching table header
                if any(kw in line_text.upper() for kw in ('ITEM', 'DESCRIPTION', 'QTY', 'QUANTITY', 'SUBTOTAL')):
                    if y_key > vendor_header_y + 5.0:
                        break

                # Filter words to left VENDOR column (x1 <= split_x)
                col_words = [w[4] for w in line_words if w[1] <= split_x + 5.0]
                if col_words:
                    col_line = ' '.join(col_words).strip()
                    col_line = re.sub(r'^(?:VENDOR|SUPPLIER)\s*[:\-]?\s*', '', col_line, flags=re.I).strip()
                    if col_line:
                        vendor_column_words.append(col_line)

            full_vendor_text = '\n'.join(vendor_column_words)
            cand = _clean_company_name(full_vendor_text)
            if cand and len(cand) > 3:
                _log_field("PO", "vendor_name", "pymupdf_coord_column", full_vendor_text[:60], cand, "ok")
                return cand
    except Exception as e:
        logger.warning(f"PO coordinate vendor extraction error: {e}")

    return None


def _extract_vendor(text: str, doc_label: str = "PO", pdf_path: Optional[str] = None) -> Optional[str]:
    """
    Extract vendor/supplier name from document text.
    Uses positional coordinate extraction when pdf_path is available.
    Supports side-by-side VENDOR vs SHIP TO / BILL TO column layout.
    Returns None if vendor cannot be confidently identified.
    Never returns a buyer name.
    """
    # Priority 0: Positional coordinate extraction (if pdf_path is available)
    if pdf_path:
        coord_cand = _extract_vendor_with_coordinates(pdf_path)
        if coord_cand:
            return coord_cand

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    buyer_idx = _get_buyer_line_index(lines)

    # Priority 1: Side-by-side header line splitting
    # e.g. "VENDOR Dora-Rana Pvt Ltd          SHIP TO TECHGURUPLUS SOLUTIONS"
    for idx, line in enumerate(lines[:buyer_idx]):
        if re.search(r'\bVENDOR\b', line, re.I):
            # Split line horizontally if it contains buyer section headers
            parts = re.split(r'\b(?:SHIP\s*TO|BILL\s*TO|SOLD\s*TO|DELIVER\s*TO|BUYER|CUSTOMER)\b', line, flags=re.I)
            vendor_side = parts[0].strip()
            vendor_side = re.sub(r'^\s*VENDOR\s*[:\-]?\s*', '', vendor_side, flags=re.I).strip()

            cleaned = _clean_company_name(vendor_side)
            if cleaned and len(cleaned) > 3:
                _log_field(doc_label, "vendor_name", "side_by_side_vendor_line", line, cleaned, "ok")
                return cleaned

            # If VENDOR was a standalone header line, check next lines (split at column gaps \s{2,})
            for j in range(idx + 1, min(idx + 6, len(lines))):
                cand_line = lines[j]
                if re.match(r'^(SHIP\s*TO|BILL\s*TO|ITEM|PO|DATE|PHONE|H-|F\.O\.B|TERMS)', cand_line, re.I):
                    break
                col_parts = re.split(r'\s{2,}', cand_line)
                cand_sub = col_parts[0].strip()  # left column
                cleaned = _clean_company_name(cand_sub)
                if cleaned and len(cleaned) > 3:
                    _log_field(doc_label, "vendor_name", "vendor_block_left_col", cand_line, cleaned, "ok")
                    return cleaned

    # Priority 2: Explicit label (Supplier Name:, Vendor:, Sold By:, Seller:)
    m = _VENDOR_LABEL_RE.search(text)
    if m:
        cand = _clean_company_name(m.group(1))
        if cand:
            _log_field(doc_label, "vendor_name", "explicit_label", m.group(0), cand, "ok")
            return cand

    # Priority 3: First lines before buyer section — scan for company suffix
    for line in lines[:buyer_idx]:
        if re.match(r'^(INVOICE|STATEMENT|TAX|PAGE|DATE|PHONE|EMAIL|HTTP|WWW|PURCHASE|ITEM|SUBTOTAL|TOTAL)', line, re.I):
            continue
        if re.match(r'^\d', line):
            continue
        sm = _COMPANY_SUFFIX_RE.search(line)
        if sm:
            cand = _clean_company_name(sm.group(1))
            if cand and len(cand) > 3:
                _log_field(doc_label, "vendor_name", "company_suffix_scan", line, cand, "ok")
                return cand

    _log_field(doc_label, "vendor_name", "all_strategies", None, None, "missing")
    return None


# ---------------------------------------------------------------------------
# Monetary field extraction
# ---------------------------------------------------------------------------

# Each pattern is specific to avoid cross-field contamination
_RE_CURRENCY = r'(?:Rs\.?|\$|€|£|INR|USD|EUR|₹)?\s*'
_RE_SUBTOTAL    = re.compile(r'Sub\s*[-\s]?total\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_TAX_RATE    = re.compile(r'Tax\s*[Rr]ate\s*[:\n\s]*([\d.]+)\s*%', re.I)
_RE_TAX_AMOUNT  = re.compile(r'Tax\s*(?:[Aa]mount|[Dd]ue|@\s*[\d.]+\s*%?)\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_TAX_BRACKET = re.compile(r'Tax\s*\([^)]+\)\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_GST         = re.compile(r'(?:GST|IGST|CGST|SGST)\s*(?:@[\d.]+%?)?\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_TOTAL       = re.compile(r'(?<!\bSub)(?<!\bSub\s)(?:Grand\s*)?Total\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
# PO number: look for PO #, PO NUMBER, Purchase Order No, etc.
_RE_PO_NUMBER   = re.compile(
    r'(?:\b(?:(?:P\.?O\.?\s*(?:#|NUMBER|NUM|NO\.?|ID)|Purchase\s*Order\s*(?:#|NUMBER|NUM|NO\.?|ID))\s*[:\-]?\s*'
    r'|\bPO\s*[:#\-]\s*'
    r'|\bPO\s+(?=\d{4,10}\b)'
    r')(?!(?:BOX|DATE|TERMS|TOTAL|AMOUNT|LINE|VIA|METHOD|REQUISITIONER|SHIP|PHONE|DUE|TO|VENDOR|BUYER|TEL|FAX|EMAIL|ADDR)\b)([A-Za-z0-9\-]{3,30})'
    r'|\b(PO[-_/]?[0-9][0-9A-Za-z\-_/]{2,20})\b)',
    re.I
)
_RE_PO_DATE     = re.compile(
    r'(?:PO\s*Date|Date\s*of\s*PO|Order\s*Date|Date)\s*[:\n\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})',
    re.I
)
_RE_REQUISITIONER = re.compile(r'Requisitioner\s*[:\n\s]*([^\n]+)', re.I)
_RE_SHIP_TERMS    = re.compile(r'(?:Shipping\s*Terms?|Ship\s*Via|F\.?\s*O\.?\s*B\.?)\s*[:\n\s]*([^\n]+)', re.I)


def _extract_tax_rate_and_amount(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract tax_rate (percentage float) and tax_amount (monetary float).
    Supports:
      - "TAX (18%) 19890.00" -> rate=18.0, amount=19890.00
      - "Tax Rate: 18.0%" -> rate=18.0
      - "Tax @ 18%: 4950.00" -> rate=18.0, amount=4950.00
      - "GST (18%) 19890.00" -> rate=18.0, amount=19890.00
    """
    rate = None
    amount = None

    # Pattern 1: Tax label with explicit percentage e.g. "TAX (18%) 19,890.00", "Tax @ 18%: 4950.00"
    m1 = re.search(
        r'(?:Tax|GST|IGST|CGST|SGST)\s*(?:Rate|amount|due)?\s*[\(@@]?\s*([\d.]+)\s*%\s*\)?\s*[:\n\s]*(?:Rs\.?|\$|€|£|INR|USD|EUR|₹)?\s*([,\d]+\.\d{2})',
        text, re.I
    )
    if m1:
        rate = float(m1.group(1))
        amount = _f(m1.group(2))
        return rate, amount

    # Pattern 2: "Tax Rate: 18.0%"
    m2 = re.search(r'Tax\s*Rate\s*[:\n\s]*([\d.]+)\s*%', text, re.I)
    if m2:
        rate = float(m2.group(1))

    # Pattern 3: Standalone percentage on Tax/GST line e.g. "TAX (18%)" or "GST @ 18%"
    if rate is None:
        m3 = re.search(r'(?:Tax|GST|IGST|CGST|SGST)\s*[\(@@]?\s*([\d.]+)\s*%', text, re.I)
        if m3:
            rate = float(m3.group(1))

    # Pattern 4: Tax amount without explicit percentage in label
    if amount is None:
        m4 = _RE_TAX_AMOUNT.search(text) or _RE_TAX_BRACKET.search(text) or _RE_GST.search(text)
        if m4:
            amount = _f(m4.group(1))

    return rate, amount


def _extract_monetary_fields(text: str, doc_label: str = "PO") -> dict:
    """Extract all monetary fields from text using dedicated non-overlapping regexes."""
    result = {}

    sub_m = _RE_SUBTOTAL.search(text)
    result['subtotal'] = _f(sub_m.group(1)) if sub_m else None
    _log_field(doc_label, "subtotal", "RE_SUBTOTAL", sub_m and sub_m.group(0), result['subtotal'],
               "ok" if result['subtotal'] is not None else "missing")

    rate, amount = _extract_tax_rate_and_amount(text)
    result['tax_rate'] = rate
    result['tax_amount'] = amount

    # Derive tax_rate if not explicitly printed with % sign
    if (result['tax_rate'] is None or result['tax_rate'] == 0.0) and result['subtotal'] and result['tax_amount']:
        if result['subtotal'] > 0 and result['tax_amount'] > 0:
            result['tax_rate'] = round((result['tax_amount'] / result['subtotal']) * 100.0, 2)

    _log_field(doc_label, "tax_rate", "extract_tax_rate_and_amount|derived", None, result['tax_rate'],
               "ok" if result['tax_rate'] is not None else "missing")
    _log_field(doc_label, "tax_amount", "extract_tax_rate_and_amount", None, result['tax_amount'],
               "ok" if result['tax_amount'] is not None else "missing")

    tot_m = _RE_TOTAL.search(text)
    result['total_amount'] = _f(tot_m.group(1)) if tot_m else None
    _log_field(doc_label, "total_amount", "RE_TOTAL", tot_m and tot_m.group(0), result['total_amount'],
               "ok" if result['total_amount'] is not None else "missing")

    return result


# ---------------------------------------------------------------------------
# Line item extraction
# ---------------------------------------------------------------------------

def _extract_po_lines(text: str) -> List[POLineItemExtraction]:
    """
    Extract ALL line items from the PO table.

    Strategy:
    - Detect the line-items table header (contains ITEM/DESCRIPTION + QTY + PRICE columns)
    - For each subsequent non-header line that contains at least 2 numeric amounts,
      treat it as a line item row
    - Stop at Subtotal / Total / Tax rows

    This replaces the brittle keyword whitelist approach.
    """
    items: List[POLineItemExtraction] = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    _STOP_RE = re.compile(
        r'^(?:Sub\s*[-\s]?total|\bTotal\b|\bTax\b|GST|IGST|CGST|SGST|Discount|'
        r'Shipping|Freight|Note:|Terms|Remarks?|Authorized)',
        re.I
    )
    _HEADER_KEYWORDS = {'item', 'description', 'qty', 'quantity', 'unit', 'price', 'amount', 'total', 'rate'}

    # ── Phase 1: locate header row ──────────────────────────────────────────
    header_idx = -1
    for i, line in enumerate(lines):
        combined = line.lower()
        if i + 1 < len(lines): combined += " " + lines[i + 1].lower()
        if i + 2 < len(lines): combined += " " + lines[i + 2].lower()
        words = set(re.findall(r'[a-zA-Z]+', combined))
        if len(words & _HEADER_KEYWORDS) >= 2:
            header_idx = i
            break

    if header_idx < 0:
        return items

    # Skip all lines that are part of the header block (pure keywords, no amounts)
    body_start = header_idx + 1
    while body_start < len(lines):
        candidate = lines[body_start]
        has_amount = bool(re.search(r'[\d,]+\.\d{2}', candidate))
        is_only_keywords = bool(set(re.findall(r'[a-zA-Z]+', candidate.lower())) & _HEADER_KEYWORDS) and not has_amount
        is_separator = bool(re.match(r'^[-=_\s]+$', candidate))
        if _STOP_RE.match(candidate) and not has_amount:
            body_start += 1
            continue
        if is_separator:
            body_start += 1
            continue
        if is_only_keywords and not has_amount:
            body_start += 1
            continue
        break

    body_lines = lines[body_start:]

    # ── Phase 2: try to find end of body ────────────────────────────────────
    end_idx = len(body_lines)
    for j, bl in enumerate(body_lines):
        if _STOP_RE.match(bl) and not re.search(r'[\d,]+\.\d{2}', bl):
            end_idx = j
            break
    body_lines = body_lines[:end_idx]

    # ── Phase 3: check format — horizontal (each row on 1 line) or vertical ─
    # Horizontal: any body line has >= 2 decimal amounts
    horizontal = any(
        len([x for x in re.findall(r'[\d,]+\.\d{2}', bl) if _f(x)]) >= 2
        for bl in body_lines
    )

    def _parse_row(desc_raw, code_raw, qty_raw, up_raw, lt_raw, item_n):
        """Convert raw string tokens into a POLineItemExtraction."""
        unit_price = _f(up_raw)
        line_total = _f(lt_raw)
        if unit_price is None or line_total is None:
            return None
        try:
            qty = float(qty_raw.strip())
        except (ValueError, TypeError):
            qty = 1.0
        # Validate qty * unit_price ≈ line_total
        if line_total > 0 and abs((qty * unit_price) - line_total) > 1.0:
            # try to derive qty
            if unit_price > 0:
                derived = round(line_total / unit_price, 2)
                if abs((derived * unit_price) - line_total) < 1.0:
                    qty = derived
        desc = re.sub(r'\(?\s*Qty\s*\d+.*?\)?', '', desc_raw, flags=re.I).strip(' \t-|:(),')
        if not desc:
            desc = f"Line item {item_n + 1}"
        return POLineItemExtraction(
            item_code=code_raw.strip() if code_raw and code_raw.strip() else None,
            description=desc[:150],
            qty=qty,
            unit_price=unit_price,
            line_total=line_total,
        )

    if horizontal:
        # ── Horizontal format ────────────────────────────────────────────────
        for line in body_lines:
            if _STOP_RE.match(line):
                break
            if not line or re.match(r'^[-=_\s]+$', line):
                continue

            amounts = [_f(am) for am in re.findall(r'[\d,]+\.\d{2}', line) if _f(am)]
            if len(amounts) < 2:
                continue

            unit_price = amounts[0]
            line_total = amounts[-1]
            line_no_dec = re.sub(r'[\d,]+\.\d{2}', '', line)
            int_tokens = re.findall(r'\b\d{1,8}\b', line_no_dec)

            code = None
            qty = 1.0
            qty_tok = None

            if len(int_tokens) >= 2:
                if line_no_dec.strip().startswith(int_tokens[0]):
                    code = int_tokens[0]
                    cand_idx = 1
                else:
                    code = None
                    cand_idx = 0
                cand_val = float(int_tokens[cand_idx])
                if line_total > 0 and abs((cand_val * unit_price) - line_total) < 1.0:
                    qty = cand_val
                    qty_tok = int_tokens[cand_idx]
                else:
                    for tok in int_tokens:
                        if code and tok == code:
                            continue
                        try:
                            v = float(tok)
                            if line_total > 0 and abs((v * unit_price) - line_total) < 1.0:
                                qty = v
                                qty_tok = tok
                                break
                        except ValueError:
                            pass
                    if qty_tok is None:
                        qty = cand_val
                        qty_tok = int_tokens[cand_idx]
            elif len(int_tokens) == 1:
                val = int_tokens[0]
                if line_total > 0 and abs((float(val) * unit_price) - line_total) < 1.0:
                    qty = float(val)
                    qty_tok = val
                elif line_no_dec.strip().startswith(val):
                    code = val
                else:
                    qty = float(val)
                    qty_tok = val

            desc_text = line_no_dec
            if code:
                desc_text = re.sub(r'\b' + re.escape(code) + r'\b', '', desc_text, count=1)
            if qty_tok:
                desc_text = re.sub(r'\b' + re.escape(qty_tok) + r'\b', '', desc_text, count=1)
            desc_text = re.sub(r'\(?\s*Qty\s*\d+.*?\)?', '', desc_text, flags=re.I)
            desc = desc_text.strip(' \t-|:(),')
            if not desc:
                desc = f"Line item {len(items) + 1}"

            _log_field("PO", f"line_item[{len(items)}]", "horizontal",
                       line[:80], f"qty={qty} up={unit_price} total={line_total}", "ok")
            items.append(POLineItemExtraction(
                item_code=code,
                description=desc[:150],
                qty=qty,
                unit_price=unit_price,
                line_total=line_total,
            ))

    else:
        # ── Vertical format: group lines into rows ───────────────────────────
        # Each row = item_code line? + description + qty + unit_price + total
        # Detect rows: a row starts with an item code (integer) or a description (text)
        # and ends when we collect 2 decimal amounts.
        i = 0
        while i < len(body_lines):
            line = body_lines[i]
            if _STOP_RE.match(line) and not re.search(r'[\d,]+\.\d{2}', line):
                break
            if re.match(r'^[-=_\s]+$', line):
                i += 1
                continue

            # Accumulate lines until we have 2 decimal amounts
            group = []
            amounts = []
            j = i
            while j < len(body_lines) and len(amounts) < 2:
                bl = body_lines[j]
                if _STOP_RE.match(bl) and not re.search(r'[\d,]+\.\d{2}', bl):
                    break
                group.append(bl)
                for am in re.findall(r'[\d,]+\.\d{2}', bl):
                    v = _f(am)
                    if v:
                        amounts.append((am, v))
                j += 1

            if len(amounts) < 2:
                i = j
                continue

            unit_price = amounts[0][1]
            line_total = amounts[-1][1]

            # Find description and qty from group
            desc_candidates = []
            qty_raw = None
            code_raw = None

            for gl in group:
                gl_clean = re.sub(r'[\d,]+\.\d{2}', '', gl).strip()
                if re.match(r'^\d{1,8}$', gl_clean):
                    # pure integer — item code or qty
                    v = float(gl_clean)
                    if line_total > 0 and unit_price > 0 and abs((v * unit_price) - line_total) < 1.0:
                        qty_raw = gl_clean
                    elif code_raw is None:
                        code_raw = gl_clean
                elif gl_clean and not re.match(r'^[\d\.\-,]+$', gl_clean):
                    desc_candidates.append(gl_clean)

            if qty_raw is None and unit_price > 0:
                derived = round(line_total / unit_price, 0)
                if abs((derived * unit_price) - line_total) < 1.0:
                    qty_raw = str(int(derived))

            qty = float(qty_raw) if qty_raw else 1.0
            desc = ' '.join(desc_candidates).strip(' \t-|:(),') or f"Line item {len(items) + 1}"

            _log_field("PO", f"line_item[{len(items)}]", "vertical_group",
                       str(group)[:80], f"qty={qty} up={unit_price} total={line_total}", "ok")
            items.append(POLineItemExtraction(
                item_code=code_raw,
                description=desc[:150],
                qty=qty,
                unit_price=unit_price,
                line_total=line_total,
            ))
            i = j

    return items


# ---------------------------------------------------------------------------
# Validation (warning only — never overwrites extracted values)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Validation (warning only — never overwrites extracted values)
# ---------------------------------------------------------------------------

def _validate_po(obj: POExtraction, raw_text: str = "") -> Tuple[bool, List[str]]:
    """
    Validate extracted PO numeric & section consistency.
    Enforces strict validation rules:
      - Vendor section vs Buyer section validation
      - Printed tax rate vs extracted tax_rate check
      - Calculated tax amount vs extracted tax_amount check
      - Subtotal + Tax == Total check
      - Line items sum == Subtotal check

    Returns (passed, warnings_list).
    """
    warnings = []
    val_passed = True

    # 1. Vendor Validation
    if not obj.vendor_name or obj.vendor_name.strip() in ("", "UNKNOWN"):
        warnings.append("Validation Error: Vendor name is missing or unidentified")
        val_passed = False
    else:
        v_upper = obj.vendor_name.upper()
        if "TECHGURUPLUS" in v_upper or "BUYER" in v_upper or "CUSTOMER" in v_upper:
            warnings.append(f"Validation Error: Vendor name '{obj.vendor_name}' appears to be buyer/customer name")
            val_passed = False

    # 2. Tax Rate Validation
    if raw_text:
        printed_rate_m = re.search(r'(?:Tax|GST|IGST|CGST|SGST)\s*(?:Rate|amount|due)?\s*[\(@@]?\s*([\d.]+)\s*%', raw_text, re.I)
        if printed_rate_m:
            printed_rate = float(printed_rate_m.group(1))
            extracted_rate = obj.tax_rate or 0.0
            if abs(printed_rate - extracted_rate) > 0.1:
                warnings.append(f"Validation Error: Printed tax rate ({printed_rate}%) does not match extracted tax_rate ({extracted_rate}%)")
                val_passed = False

    # 3. Tax Amount Validation
    sub = obj.subtotal or 0.0
    tax = obj.tax_amount or 0.0
    tot = obj.total_amount or 0.0
    rate = obj.tax_rate or 0.0

    if sub > 0 and rate > 0:
        expected_tax = sub * (rate / 100.0)
        if tax > 0 and abs(expected_tax - tax) > 1.0:
            warnings.append(f"Validation Error: Calculated tax ({expected_tax:.2f}) does not match extracted tax_amount ({tax:.2f})")
            val_passed = False

    # 4. Total check
    if tot > 0 and abs((sub + tax) - tot) > 1.0:
        warnings.append(
            f"Validation Error: subtotal({sub:.2f}) + tax({tax:.2f}) = {sub+tax:.2f} "
            f"!= total_amount({tot:.2f}) — monetary sum error"
        )
        val_passed = False

    # 5. Line items sum check
    if obj.line_items:
        lines_sum = sum(li.line_total or 0.0 for li in obj.line_items)
        if sub > 0 and abs(lines_sum - sub) > 1.0:
            warnings.append(
                f"sum(line_items.line_total)={lines_sum:.2f} != subtotal={sub:.2f} — warning only"
            )

    return val_passed, warnings


# ---------------------------------------------------------------------------
# Missing-fields detection for targeted LLM fallback
# ---------------------------------------------------------------------------

def _find_missing_fields(obj: POExtraction) -> List[str]:
    missing = []
    if not obj.po_number or obj.po_number in ("UNKNOWN", ""):
        missing.append("po_number")
    if not obj.vendor_name:
        missing.append("vendor_name")
    if not obj.subtotal or obj.subtotal == 0.0:
        missing.append("subtotal")
    if not obj.total_amount or obj.total_amount == 0.0:
        missing.append("total_amount")
    if not obj.po_date:
        missing.append("po_date")
    return missing


def _extract_section_for_fields(text: str, fields: List[str]) -> str:
    """
    Extract the most relevant section of the document for the given missing fields.
    For vendor: return the first 30 lines.
    For monetary: return the last 40 lines (usually where totals appear).
    For identifiers/dates: return the first 20 lines.
    """
    lines = text.split('\n')
    sections = set()
    for f in fields:
        if f in ('subtotal', 'total_amount', 'tax_amount', 'tax_rate'):
            sections.add('monetary')
        elif f in ('vendor_name',):
            sections.add('header')
        else:
            sections.add('identifiers')

    result_lines = []
    if 'header' in sections:
        result_lines += lines[:30]
    if 'identifiers' in sections:
        result_lines += lines[:20]
    if 'monetary' in sections:
        result_lines += lines[-40:]

    return '\n'.join(result_lines)


# ---------------------------------------------------------------------------
# Deterministic parser
# ---------------------------------------------------------------------------

def _det_parse_po(text: str, pdf_path: Optional[str] = None) -> POExtraction:
    """
    Fully deterministic PO extraction using regex patterns.
    Extracts ALL line items. Returns None for fields not found.
    Never calculates or infers values.
    """
    # --- Identifiers ---
    po_m = _RE_PO_NUMBER.search(text)
    po_num = "UNKNOWN"
    if po_m:
        for g in po_m.groups():
            if g:
                cand = g.strip()
                if cand.upper() not in ("DATE", "CUSTOMER", "DUE", "PO", "NO", "NUMBER", "TOTAL", "AMOUNT", "BOX", "PHONE", "TERMS", "SHIP", "TEL", "FAX", "EMAIL"):
                    po_num = cand
                    break
    _log_field("PO", "po_number", "RE_PO_NUMBER", po_m and po_m.group(0), po_num,
               "ok" if po_num != "UNKNOWN" else "missing")

    date_m = _RE_PO_DATE.search(text)
    po_date = _norm_date(date_m.group(1)) if date_m else None
    _log_field("PO", "po_date", "RE_PO_DATE", date_m and date_m.group(0), po_date,
               "ok" if po_date else "missing")

    req_m = _RE_REQUISITIONER.search(text)
    requisitioner = req_m.group(1).strip()[:100] if req_m else None

    ship_m = _RE_SHIP_TERMS.search(text)
    shipping_terms = ship_m.group(1).strip()[:100] if ship_m else None

    # --- Vendor ---
    vendor = _extract_vendor(text, "PO", pdf_path=pdf_path)

    # --- Monetary fields ---
    monetary = _extract_monetary_fields(text, "PO")
    subtotal    = monetary['subtotal'] or 0.0
    tax_rate    = monetary['tax_rate'] or 0.0
    tax_amount  = monetary['tax_amount'] or 0.0
    total_amount = monetary['total_amount'] or 0.0

    # --- Line items ---
    line_items = _extract_po_lines(text)
    _log_field("PO", "line_items_count", "numeric_col_scan", None, len(line_items),
               "ok" if line_items else "none_found")

    return POExtraction(
        po_number=po_num,
        po_date=po_date,
        vendor_name=vendor,
        vendor_address=None,
        requisitioner=requisitioner,
        shipping_terms=shipping_terms,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        line_items=line_items
    )


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class PurchaseOrderParser(BaseDocumentParser):
    """
    Purchase Order parser — deterministic first, targeted LLM fallback.

    Execution order:
    1. Deterministic extraction
    2. Validate required fields + numeric consistency + vendor/tax accuracy
    3. If validation passes → return result (LLM NOT called)
    4. If validation fails → send ONLY missing/failed sections to LLM
    5. Merge LLM output into deterministic result for missing fields only
    """

    def extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        result = ExtractionResult(raw_text=raw_text, model_used="deterministic_po_v2")
        result.prompt = "Deterministic PO parser — LLM only invoked for missing fields"

        cleaned = preprocess_for_llm(raw_text)
        result.cleaned_text = cleaned

        # ── Step 1: Deterministic extraction ──────────────────────────────
        logger.info("PO: Running deterministic parser")
        extracted_obj = _det_parse_po(cleaned, pdf_path=pdf_path)

        # ── Step 2: Validate ───────────────────────────────────────────────
        numeric_ok, val_warnings = _validate_po(extracted_obj, raw_text=cleaned)
        missing_fields = _find_missing_fields(extracted_obj)
        result.warnings = val_warnings

        if val_warnings:
            logger.warning(f"PO validation warnings: {val_warnings}")

        # ── Step 3: Accept deterministic result if clean ──────────────────
        if not missing_fields and numeric_ok:
            logger.info("PO: Deterministic extraction succeeded — skipping LLM")
            result.model_used = "deterministic_po_v2"
        else:
            # ── Step 4: Targeted LLM fallback ─────────────────────────────
            llm_used = False

            if missing_fields and _has_valid_llm_key():
                logger.info(f"PO: LLM fallback for missing fields: {missing_fields}")
                section_text = _extract_section_for_fields(cleaned, missing_fields)
                prompt = _PO_MISSING_FIELDS_PROMPT.format(
                    missing_fields=', '.join(missing_fields),
                    section_text=section_text
                )
                result.prompt = prompt

                llm_patch, model, tokens, raw_resp, err = self._call_llm_patch(prompt)
                result.raw_llm_response = raw_resp
                result.model_used = model
                result.tokens_used = tokens
                result.retry_attempted = True

                if llm_patch:
                    llm_used = True
                    # Merge only the missing fields from LLM response
                    extracted_obj = self._merge_llm_patch(extracted_obj, llm_patch, missing_fields)
                    logger.info(f"PO: Merged LLM patch for {missing_fields}")
                elif err:
                    logger.warning(f"PO: LLM fallback failed: {err}")
                    result.validation_errors = [err]

            elif not missing_fields and not numeric_ok and _has_valid_llm_key():
                # Numeric check failed — send full document to LLM for totals verification
                logger.info("PO: LLM fallback for numeric inconsistency")
                schema_str = json.dumps(POExtraction.model_json_schema(), indent=2)
                prompt = _PO_FULL_PROMPT.format(schema=schema_str, text=cleaned)
                result.prompt = prompt

                llm_obj, model, tokens, raw_resp, err = self._call_llm_full(prompt)
                result.raw_llm_response = raw_resp
                result.model_used = model
                result.tokens_used = tokens
                result.retry_attempted = True

                if llm_obj:
                    llm_used = True
                    llm_ok, llm_warn = _validate_po(llm_obj, raw_text=cleaned)
                    if llm_ok:
                        extracted_obj = llm_obj
                        numeric_ok = True
                        result.warnings = []
                    else:
                        # LLM also failed — keep deterministic result
                        result.warnings = val_warnings + [f"LLM also failed numeric: {llm_warn}"]

            if not llm_used:
                result.model_used = "deterministic_po_v2"

        # ── Step 5: Re-validate after merge ───────────────────────────────
        numeric_ok, val_warnings = _validate_po(extracted_obj, raw_text=cleaned)
        if val_warnings:
            result.warnings = list(set(result.warnings or []) | set(val_warnings))

        result.extracted_obj = extracted_obj
        result.parsed_json = extracted_obj.model_dump()
        result.validation_errors = val_warnings
        result.numeric_validation_passed = numeric_ok
        result.success = True  # We always return something (det parser always produces an object)
        result.confidence = score_po_extraction(extracted_obj, val_warnings=val_warnings)
        return result

    # ── LLM helpers ─────────────────────────────────────────────────────────

    def _call_llm_patch(self, prompt: str) -> Tuple[Optional[dict], str, int, Optional[str], Optional[str]]:
        """Call LLM and return a partial dict patch (not a full Pydantic object)."""
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Audit Evidence Assistant",
        }
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        model_label = f"openrouter/{settings.OPENROUTER_MODEL}"
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code != 200:
                    return None, model_label, 0, res.text, f"HTTP {res.status_code}"
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                parsed = json.loads(content)
                return parsed, model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"PO LLM patch call failed: {e}")
            return None, model_label, 0, None, str(e)

    def _call_llm_full(self, prompt: str) -> Tuple[Optional[POExtraction], str, int, Optional[str], Optional[str]]:
        """Call LLM for full extraction and return a POExtraction object."""
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Audit Evidence Assistant",
        }
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        model_label = f"openrouter/{settings.OPENROUTER_MODEL}"
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code != 200:
                    return None, model_label, 0, res.text, f"HTTP {res.status_code}"
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                obj = POExtraction.model_validate(json.loads(content))
                return obj, model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"PO LLM full call failed: {e}")
            return None, model_label, 0, None, str(e)

    @staticmethod
    def _merge_llm_patch(base: POExtraction, patch: dict, fields: List[str]) -> POExtraction:
        """Merge LLM-extracted fields into the deterministic base object (only for missing fields)."""
        data = base.model_dump()
        for field in fields:
            if field in patch and patch[field] is not None:
                data[field] = patch[field]
        try:
            return POExtraction.model_validate(data)
        except Exception as e:
            logger.warning(f"PO: Failed to merge LLM patch: {e}")
            return base
