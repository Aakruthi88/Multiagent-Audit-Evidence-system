"""
invoice_parser.py
-----------------
Invoice document parser.

Extraction strategy:
  1. Deterministic parser runs FIRST (regex + PyMuPDF text)
  2. Validate result (required fields + numeric consistency)
  3. LLM fallback ONLY if mandatory fields are missing or numeric check fails
  4. LLM receives ONLY the section containing missing fields, not the full document
  5. Compute rubric-based confidence score

Key rules:
  - Never calculate/infer monetary values — extract exactly what is printed
  - vendor_name returns None (not "Unknown Vendor") if not confidently found
  - Never confuse Bill To / Ship To / Customer / Buyer with Vendor
  - All line items are extracted (not just the first)
  - Supports GST, IGST, CGST, SGST, plain Tax
  - Validation generates warnings only — never overwrites extracted values
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Any

import httpx

from app.core.config import settings
from app.schemas.extraction_schemas import InvoiceExtraction, InvoiceLineItemExtraction
from app.services.parsers.base_parser import BaseDocumentParser, ExtractionResult
from app.services.parsers.text_utils import (
    preprocess_for_llm,
    clean_float,
    normalize_date,
    log_field_extraction,
)
from app.services.confidence import score_invoice_extraction

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
# LLM Prompts
# ---------------------------------------------------------------------------

_INV_MISSING_FIELDS_PROMPT = """You are a precise document data extractor specializing in Invoices.

The deterministic parser already extracted most fields successfully.
Only the following fields could NOT be extracted: {missing_fields}

Look at the relevant section of the Invoice below and extract ONLY those missing fields.
Return ONLY a valid JSON object containing those field names as keys.

RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate. If a field is genuinely missing, return null for it.
- vendor_name = the SELLER at the TOP of the invoice. NEVER use Bill To / Ship To / Customer / Buyer.
- Dates must be in YYYY-MM-DD format.
- Monetary amounts must be floats (no currency symbols).

Missing fields to extract: {missing_fields}

Document section:
{section_text}
"""

_INV_FULL_PROMPT = """You are a precise document data extractor specializing in Invoices.

Extract ALL structured data from the Invoice text below and return ONLY valid JSON.

CRITICAL RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate values. If a field is not present, return null.
- Preserve identifiers (invoice numbers, PO references) EXACTLY as written.
- vendor_name = the SELLER / SUPPLIER at the TOP of the invoice.
  NEVER use Bill To, Ship To, Customer, or Receiver as vendor_name.
- Dates must be in YYYY-MM-DD format.
- All monetary amounts must be floats (no currency symbols in values).
- line_items must contain EVERY line item row from the invoice table.
- po_ref_raw = the PO number referenced on this invoice.

JSON Schema:
{schema}

Invoice Text:
{text}
"""


# ---------------------------------------------------------------------------
# Helpers (DRY - centralized in text_utils)
# ---------------------------------------------------------------------------

_f = clean_float
_norm_date = normalize_date
_log_field = log_field_extraction


# ---------------------------------------------------------------------------
# Vendor extraction (shared with PO approach)
# ---------------------------------------------------------------------------

_BUYER_SECTION_RE = re.compile(
    r'\b(BILL\s*TO|SHIP\s*TO|SOLD\s*TO|DELIVER\s*TO|CUSTOMER|BUYER|RECEIVER|CONSIGNEE)\b',
    re.I
)

_COMPANY_SUFFIX_RE = re.compile(
    r'([A-Za-z0-9\s&,\-\'.]+?\b(?:'
    r'Pvt\.?\s*Ltd\.?|Private\s*Limited|Ltd\.?|Inc\.?|Corp\.?|LLC|'
    r'Solutions|Technologies|Industries|Enterprises?|Services?|'
    r'Traders?|Suppliers?|Infotech|Systems|Global|Logistics|Motors|'
    r'Manufacturing|Trading|Distributors?|Exports?|Imports?|Holdings?'
    r')\b)',
    re.I
)

_VENDOR_LABEL_RE = re.compile(
    r'(?:Supplier\s*Name|Vendor\s*Name|Supplier|Vendor|Sold\s*By|Seller|From)\s*[:\-]\s*([^\n]+)',
    re.I
)


def _get_buyer_line_index(lines: List[str]) -> int:
    for i, line in enumerate(lines):
        if _BUYER_SECTION_RE.search(line):
            return i
    return len(lines)


def _clean_company_name(name: str) -> Optional[str]:
    if not name:
        return None
    name = re.sub(
        r'^(?:Supplier\s*Name|Supplier|Vendor\s*Name|Vendor|From|Company|Seller|Sold\s*By)\s*[:\-]?\s*',
        '', name, flags=re.I
    )
    name = re.split(
        r'(?i)\b(?:Phone|Tel|Email|Address|PO\b|Date|Bill|Ship|Attn|Contact|H\.No|H-|Fax|GST|GSTIN|Due)\b',
        name
    )[0]
    name = name.strip(' :,;-\n\r\t')
    return name if len(name) > 2 else None


def _extract_vendor(text: str, doc_label: str = "Invoice") -> Optional[str]:
    """
    Extract vendor/supplier name from invoice text.
    Vendor = the SELLER at the top of the invoice.
    Returns None if not confidently identified.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Find the boundary where buyer section starts
    buyer_idx = _get_buyer_line_index(lines)

    # Also look for Invoice # line as an upper bound
    for i, line in enumerate(lines):
        if re.search(r'\bINVOICE\s*(?:#|NO|NUMBER)\b', line, re.I):
            # Vendor is typically above invoice# line on seller-header invoices
            # but the invoice# line itself might be PART of the header
            # So don't cut off earlier than line 3
            if i > 3:
                buyer_idx = min(buyer_idx, i)
            break

    # Priority 1: Explicit label
    m = _VENDOR_LABEL_RE.search(text)
    if m:
        # Ensure this label appears before the buyer section
        label_line_idx = text[:m.start()].count('\n')
        if label_line_idx < buyer_idx + 2:
            cand = _clean_company_name(m.group(1))
            if cand:
                _log_field(doc_label, "vendor_name", "explicit_label", m.group(0), cand, "ok")
                return cand

    # Priority 2: First non-header lines before buyer section
    # 
    _VENDOR_LABEL_RE = re.compile(
    r'(?:Supplier\s*Name|Vendor\s*Name|Supplier|Vendor|Sold\s*By|Seller|From)\s*[:\-]\s*([^\n]+)',
    re.I
)

# NEW: a line that is ONLY a wrapped company suffix (e.g. "Ltd" alone on its own
# line, because the PDF wrapped "...Pvt Ltd" across two lines)
_COMPANY_CONTINUATION_RE = re.compile(
    r'^(?:Ltd\.?|Limited|LLC|Inc\.?|Corp\.?|Pvt\.?\s*Ltd\.?|Private\s*Limited)$', re.I
)


def _get_buyer_line_index(lines: List[str]) -> int:
    for i, line in enumerate(lines):
        if _BUYER_SECTION_RE.search(line):
            return i
    return len(lines)


def _maybe_join_next_line(lines: List[str], idx: int) -> str:
    """If the next line is just a wrapped company suffix, join it onto this line."""
    line = lines[idx]
    if idx + 1 < len(lines) and _COMPANY_CONTINUATION_RE.match(lines[idx + 1].strip()):
        return f"{line} {lines[idx + 1].strip()}"
    return line


def _clean_company_name(name: str) -> Optional[str]:
    if not name:
        return None
    name = re.sub(
        r'^(?:Supplier\s*Name|Supplier|Vendor\s*Name|Vendor|From|Company|Seller|Sold\s*By)\s*[:\-]?\s*',
        '', name, flags=re.I
    )
    name = re.split(
        r'(?i)\b(?:Phone|Tel|Email|Address|PO\b|Date|Bill|Ship|Attn|Contact|H\.No|H-|Fax|GST|GSTIN|Due)\b',
        name
    )[0]
    name = name.strip(' :,;-\n\r\t')
    return name if len(name) > 2 else None


def _extract_vendor(text: str, doc_label: str = "Invoice") -> Optional[str]:
    """
    Extract vendor/supplier name from invoice text.
    Vendor = the SELLER at the top of the invoice.
    Returns None if not confidently identified.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Find the boundary where buyer section starts
    buyer_idx = _get_buyer_line_index(lines)

    # Also look for Invoice # line as an upper bound
    for i, line in enumerate(lines):
        if re.search(r'\bINVOICE\s*(?:#|NO|NUMBER)\b', line, re.I):
            if i > 3:
                buyer_idx = min(buyer_idx, i)
            break

    # Priority 1: Explicit label
    m = _VENDOR_LABEL_RE.search(text)
    if m:
        label_line_idx = text[:m.start()].count('\n')
        if label_line_idx < buyer_idx + 2:
            cand = _clean_company_name(m.group(1))
            if cand:
                _log_field(doc_label, "vendor_name", "explicit_label", m.group(0), cand, "ok")
                return cand

    # Priority 2: First non-header lines before buyer section
    skip_re = re.compile(
        r'^(INVOICE|TAX\s*INVOICE|STATEMENT|PAGE|PHONE|EMAIL|HTTP|WWW|GST|GSTIN)',
        re.I
    )
    for idx, line in enumerate(lines[:buyer_idx]):
        if skip_re.match(line):
            continue
        if re.match(r'^\d', line):
            continue
        if len(line) < 3:
            continue
        line = _maybe_join_next_line(lines, idx)  # FIX: join wrapped "...Pvt\nLtd" names
        sm = _COMPANY_SUFFIX_RE.search(line)
        if sm:
            cand = _clean_company_name(sm.group(1))
            if cand and len(cand) > 3:
                _log_field(doc_label, "vendor_name", "company_suffix_scan", line, cand, "ok")
                return cand
        cleaned = _clean_company_name(line)
        if cleaned and len(cleaned) > 5 and not re.search(r'\d{6,}', cleaned):
            _log_field(doc_label, "vendor_name", "header_line_scan", line, cleaned, "ok")
            return cleaned

    _log_field(doc_label, "vendor_name", "all_strategies", None, None, "missing")
    return None

# ---------------------------------------------------------------------------
# Monetary field extraction
# ---------------------------------------------------------------------------

_RE_CURRENCY = r'(?:Rs\.?|\$|€|£|INR|USD|EUR|₹)?\s*'
_RE_SUBTOTAL    = re.compile(r'Sub\s*[-\s]?total\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_TAX_RATE    = re.compile(r'Tax\s*[Rr]ate\s*[:\n\s]*([\d.]+)\s*%', re.I)
# Tax amount: explicit "Tax amount", "Tax due", "Tax @ 18%", "Tax (18%)"
_RE_TAX_AMOUNT  = re.compile(r'Tax\s*(?:[Aa]mount|[Dd]ue|@\s*[\d.]+\s*%?)\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
_RE_TAX_BRACKET = re.compile(r'Tax\s*\([^)]+\)\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
# GST variants — IGST, CGST, SGST, plain GST
_RE_GST         = re.compile(r'(?:GST|IGST|CGST|SGST)\s*(?:@[\d.]+%?)?\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
# Grand Total — must NOT match Subtotal
_RE_TOTAL       = re.compile(r'(?<!\bSub)(?<!\bSub\s)(?:Grand\s*)?Total\s*[:\n\s]*' + _RE_CURRENCY + r'([,\d]+\.\d{2})', re.I)
# Invoice-specific fields
_RE_INV_NUMBER  = re.compile(
    r'(?:\b(?:(?:Tax\s+Invoice|INVOICE|Invoice)\s*(?:#|NUMBER|NUM|NO\.?|ID)|Tax\s+Invoice\s*:)\s*[:\-]?\s*'
    r'|\bInvoice\s*[:#\-]\s*'
    r'|\bInvoice\s+(?=\d{4,10}\b)'
    r')(?!(?:DATE|DUE|TOTAL|AMOUNT|SUBTOTAL|TAX|NET|ITEM|BILL|SHIP|TO|FOR|CUST|VENDOR|PHONE|TEL|FAX|EMAIL|ADDR)\b)([A-Za-z0-9\-\/]{3,30})'
    r'|\b(INV[-_/]?[0-9][0-9A-Za-z\-_/]{2,20})\b',
    re.I
)
_RE_PO_REF      = re.compile(
    r'(?:\b(?:PO\s*(?:REF|Reference|No\.?|Number|#)|Purchase\s*Order\s*(?:REF|Reference|No\.?|Number|#))\s*[:\-]?\s*'
    r'|\bPO\s*[:#\-]\s*'
    r'|\bPO\s+(?=\d{4,10}\b)'
    r')(?!(?:BOX|DATE|TERMS|TOTAL|AMOUNT|LINE|VIA|METHOD|REQUISITIONER|SHIP|PHONE|DUE|TO|VENDOR|BUYER|TEL|FAX|EMAIL|ADDR)\b)([A-Za-z0-9\-]{3,30})'
    r'|\b(PO[-_/]?[0-9][0-9A-Za-z\-_/]{2,20})\b',
    re.I
)
_RE_INV_DATE    = re.compile(
    r'(?<!DUE\s)(?:Invoice\s*)?Date\s*[:\n\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})',
    re.I
)
_RE_DUE_DATE    = re.compile(
    r'Due\s*Date\s*[:\n\s]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})',
    re.I
)


def _extract_monetary_fields_inv(text: str) -> dict:
    result = {}

    sub_m = _RE_SUBTOTAL.search(text)
    result['subtotal'] = _f(sub_m.group(1)) if sub_m else None
    _log_field("Invoice", "subtotal", "RE_SUBTOTAL", sub_m and sub_m.group(0), result['subtotal'],
               "ok" if result['subtotal'] is not None else "missing")

    rate_m = _RE_TAX_RATE.search(text)
    result['tax_rate'] = float(rate_m.group(1)) if rate_m else None

    tax_m = _RE_TAX_AMOUNT.search(text) or _RE_TAX_BRACKET.search(text) or _RE_GST.search(text)
    result['tax_amount'] = _f(tax_m.group(1)) if tax_m else None

    # Derive tax_rate if not explicitly printed with % sign
    if (result['tax_rate'] is None or result['tax_rate'] == 0.0) and result['subtotal'] and result['tax_amount']:
        if result['subtotal'] > 0 and result['tax_amount'] > 0:
            result['tax_rate'] = round((result['tax_amount'] / result['subtotal']) * 100.0, 2)

    _log_field("Invoice", "tax_rate", "RE_TAX_RATE|derived", None, result['tax_rate'],
               "ok" if result['tax_rate'] is not None else "missing")
    _log_field("Invoice", "tax_amount", "RE_TAX|GST", tax_m and tax_m.group(0), result['tax_amount'],
               "ok" if result['tax_amount'] is not None else "missing")

    tot_m = _RE_TOTAL.search(text)
    result['total_amount'] = _f(tot_m.group(1)) if tot_m else None
    _log_field("Invoice", "total_amount", "RE_TOTAL", tot_m and tot_m.group(0), result['total_amount'],
               "ok" if result['total_amount'] is not None else "missing")

    return result


# ---------------------------------------------------------------------------
# Line item extraction
# ---------------------------------------------------------------------------

def _extract_inv_lines(text: str) -> List[InvoiceLineItemExtraction]:
    """
    Extract ALL invoice line items from the invoice table.

    Strategy:
    - Find the line-item table header (2+ column keywords)
    - Parse every subsequent line that has 2+ numeric amounts as a line item
    - Stop at Subtotal / Total / Tax / Grand Total rows
    """
    items: List[InvoiceLineItemExtraction] = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    _STOP_RE = re.compile(
        r'^(?:Sub\s*[-\s]?total|\bTotal\b|\bTax\b|GST|IGST|CGST|SGST|Discount|'
        r'Shipping|Freight|Note:|Terms|Remarks?|Authorized)',
        re.I
    )
    _HEADER_KEYWORDS = {'item', 'description', 'qty', 'quantity', 'unit', 'price', 'amount', 'total', 'rate', 'particulars'}

    in_table = False

    for i, line in enumerate(lines):
        if not in_table:
            combined = line.lower()
            if i + 1 < len(lines):
                combined += " " + lines[i + 1].lower()
            if i + 2 < len(lines):
                combined += " " + lines[i + 2].lower()
            words = set(re.findall(r'[a-zA-Z]+', combined))
            if len(words & _HEADER_KEYWORDS) >= 2:
                in_table = True
            continue

        if _STOP_RE.match(line):
            break

        if not line or re.match(r'^[-=_\s]+$', line):
            continue

        # Collect decimal amounts from the CURRENT line first
        current_line_amounts = [_f(am) for am in re.findall(r'[\d,]+\.\d{2}', line) if _f(am) is not None and _f(am) > 0]

        if len(current_line_amounts) >= 2:
            num_values = current_line_amounts
        else:
            num_values = []
            scan_lines = lines[i:min(i + 3, len(lines))]
            for sl in scan_lines:
                if _STOP_RE.match(sl):
                    break
                for am in re.findall(r'[\d,]+\.\d{2}', sl):
                    v = _f(am)
                    if v is not None and v > 0:
                        num_values.append(v)

        if len(num_values) < 2:
            continue

        unit_price = num_values[0]
        line_total = num_values[-1]

        # Isolate text without decimal amounts
        line_no_decimals = re.sub(r'[\d,]+\.\d{2}', '', line)

        # Try to find explicit "Qty X x Unit" pattern first
        qty_x = re.search(r'Qty\s*(\d+)\s*x\s*([\d,]+\.\d{2})', line, re.I)
        qty_tok = None
        if qty_x:
            qty = float(qty_x.group(1))
            unit_price = _f(qty_x.group(2)) or unit_price
            code = None
            int_tokens = []
        else:
            int_tokens = re.findall(r'\b\d{1,8}\b', line_no_decimals)
            code = None
            qty = 1.0

            if len(int_tokens) >= 2:
                if line_no_decimals.strip().startswith(int_tokens[0]):
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
                    found_reconcile = False
                    for tok in int_tokens:
                        if code and tok == code:
                            continue
                        try:
                            v = float(tok)
                            if line_total > 0 and abs((v * unit_price) - line_total) < 1.0:
                                qty = v
                                qty_tok = tok
                                found_reconcile = True
                                break
                        except ValueError:
                            pass
                    if not found_reconcile:
                        logger.warning(
                            f"Invoice line item qty ({int_tokens[cand_idx]}) does not reconcile with unit_price ({unit_price}) and line_total ({line_total})"
                        )
                        qty = cand_val
                        qty_tok = int_tokens[cand_idx]

            elif len(int_tokens) == 1:
                val = int_tokens[0]
                if line_total > 0 and abs((float(val) * unit_price) - line_total) < 1.0:
                    qty = float(val)
                    qty_tok = val
                    code = None
                else:
                    if line_no_decimals.strip().startswith(val):
                        code = val
                        qty = 1.0
                        qty_tok = None
                    else:
                        qty = float(val)
                        qty_tok = val

        # Description is text excluding item_code, integer tokens, and decimal amounts
        desc_text = line_no_decimals
        if code:
            desc_text = re.sub(r'\b' + re.escape(code) + r'\b', '', desc_text, count=1)
        if qty_tok:
            desc_text = re.sub(r'\b' + re.escape(qty_tok) + r'\b', '', desc_text, count=1)

        desc_text = re.sub(r'\(?\s*Qty\s*\d+.*?\)?', '', desc_text, flags=re.I)
        desc_text = re.sub(r'\bx\b', '', desc_text, flags=re.I)  # strip bare 'x' column multiplier
        desc = desc_text.strip(' \t-|:(),')
        if not desc:
            desc = f"Line item {len(items)+1}"

        _log_field("Invoice", f"line_item[{len(items)}]", "numeric_col_detect",
                   line[:80], f"qty={qty} up={unit_price} total={line_total}", "ok")

        items.append(InvoiceLineItemExtraction(
            description=desc[:150],
            qty=qty,
            unit_price=unit_price,
            line_total=line_total
        ))

    return items


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_invoice(obj: InvoiceExtraction) -> Tuple[bool, List[str]]:
    warnings = []
    sub = obj.subtotal or 0.0
    tax = obj.tax_amount or 0.0
    tot = obj.total_amount or 0.0

    if tot > 0 and abs((sub + tax) - tot) > 1.0:
        warnings.append(
            f"subtotal({sub:.2f}) + tax({tax:.2f}) = {sub+tax:.2f} "
            f"!= total_amount({tot:.2f}) — possible extraction error"
        )

    if obj.line_items:
        lines_sum = sum(li.line_total or 0.0 for li in obj.line_items)
        if sub > 0 and abs(lines_sum - sub) > 1.0:
            warnings.append(
                f"sum(line_items.line_total)={lines_sum:.2f} != subtotal={sub:.2f} — warning only"
            )

    return len(warnings) == 0, warnings


def _find_missing_fields_inv(obj: InvoiceExtraction) -> List[str]:
    missing = []
    if not obj.invoice_number or obj.invoice_number in ("UNKNOWN", ""):
        missing.append("invoice_number")
    if not obj.vendor_name:
        missing.append("vendor_name")
    if not obj.subtotal or obj.subtotal == 0.0:
        missing.append("subtotal")
    if not obj.total_amount or obj.total_amount == 0.0:
        missing.append("total_amount")
    if not obj.invoice_date:
        missing.append("invoice_date")
    return missing


def _extract_section_for_fields(text: str, fields: List[str]) -> str:
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

def _det_parse_invoice(text: str) -> InvoiceExtraction:
    """Fully deterministic invoice extraction. Returns None for fields not found."""

    # Invoice number — must not capture words like DATE, CUSTOMER, DUE
    inv_m = _RE_INV_NUMBER.search(text)
    inv_num = "UNKNOWN"
    if inv_m:
        for g in inv_m.groups():
            if g:
                cand = g.strip()
                if cand.upper() not in ("DATE", "CUSTOMER", "DUE", "PO", "NO", "NUMBER", "TOTAL", "AMOUNT", "TAX", "SUBTOTAL", "PHONE", "TEL", "FAX", "EMAIL", "BILL", "SHIP", "TO", "FOR"):
                    inv_num = cand
                    break
    _log_field("Invoice", "invoice_number", "RE_INV_NUMBER", inv_m and inv_m.group(0), inv_num,
               "ok" if inv_num != "UNKNOWN" else "missing")

    po_m = _RE_PO_REF.search(text)
    po_ref = None
    if po_m:
        for g in po_m.groups():
            if g:
                cand = g.strip()
                if cand.upper() not in ("DATE", "CUSTOMER", "DUE", "PO", "NO", "NUMBER", "TOTAL", "AMOUNT", "BOX", "PHONE", "TERMS", "SHIP", "TEL", "FAX", "EMAIL"):
                    po_ref = cand
                    break
    _log_field("Invoice", "po_ref_raw", "RE_PO_REF", po_m and po_m.group(0), po_ref,
               "ok" if po_ref else "missing")

    # Due date must be found before Invoice Date to avoid confusion
    due_m = _RE_DUE_DATE.search(text)
    due_date = _norm_date(due_m.group(1)) if due_m else None

    # Invoice date — skip if it matches the due date match
    date_m = _RE_INV_DATE.search(text)
    inv_date = None
    if date_m:
        # Ensure we didn't accidentally match the due date position
        if not due_m or abs(date_m.start() - due_m.start()) > 5:
            inv_date = _norm_date(date_m.group(1))
    _log_field("Invoice", "invoice_date", "RE_INV_DATE", date_m and date_m.group(0), inv_date,
               "ok" if inv_date else "missing")
    _log_field("Invoice", "due_date", "RE_DUE_DATE", due_m and due_m.group(0), due_date,
               "ok" if due_date else "missing")

    vendor = _extract_vendor(text, "Invoice")

    monetary = _extract_monetary_fields_inv(text)
    subtotal     = monetary['subtotal'] or 0.0
    tax_rate     = monetary['tax_rate'] or 0.0
    tax_amount   = monetary['tax_amount'] or 0.0
    total_amount = monetary['total_amount'] or 0.0

    line_items = _extract_inv_lines(text)
    _log_field("Invoice", "line_items_count", "numeric_col_scan", None, len(line_items),
               "ok" if line_items else "none_found")

    return InvoiceExtraction(
        invoice_number=inv_num,
        invoice_date=inv_date,
        due_date=due_date,
        po_ref_raw=po_ref,
        vendor_name=vendor,
        vendor_address=None,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total_amount=total_amount,
        line_items=line_items
    )


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class InvoiceParser(BaseDocumentParser):
    """
    Invoice parser — deterministic first, targeted LLM fallback.
    """

    def extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        result = ExtractionResult(raw_text=raw_text, model_used="deterministic_invoice_v2")
        result.prompt = "Deterministic Invoice parser — LLM only invoked for missing fields"

        cleaned = preprocess_for_llm(raw_text)
        result.cleaned_text = cleaned

        logger.info("Invoice: Running deterministic parser")
        extracted_obj = _det_parse_invoice(cleaned)

        numeric_ok, val_warnings = _validate_invoice(extracted_obj)
        missing_fields = _find_missing_fields_inv(extracted_obj)
        result.warnings = val_warnings

        if val_warnings:
            logger.warning(f"Invoice validation warnings: {val_warnings}")

        if not missing_fields and numeric_ok:
            logger.info("Invoice: Deterministic extraction succeeded — skipping LLM")
            result.model_used = "deterministic_invoice_v2"
        else:
            llm_used = False

            if missing_fields and _has_valid_llm_key():
                logger.info(f"Invoice: LLM fallback for missing fields: {missing_fields}")
                section_text = _extract_section_for_fields(cleaned, missing_fields)
                prompt = _INV_MISSING_FIELDS_PROMPT.format(
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
                    extracted_obj = self._merge_llm_patch(extracted_obj, llm_patch, missing_fields)
                elif err:
                    logger.warning(f"Invoice: LLM fallback failed: {err}")
                    result.validation_errors = [err]

            elif not missing_fields and not numeric_ok and _has_valid_llm_key():
                logger.info("Invoice: LLM fallback for numeric inconsistency")
                schema_str = json.dumps(InvoiceExtraction.model_json_schema(), indent=2)
                prompt = _INV_FULL_PROMPT.format(schema=schema_str, text=cleaned)
                result.prompt = prompt

                llm_obj, model, tokens, raw_resp, err = self._call_llm_full(prompt)
                result.raw_llm_response = raw_resp
                result.model_used = model
                result.tokens_used = tokens
                result.retry_attempted = True

                if llm_obj:
                    llm_used = True
                    llm_ok, llm_warn = _validate_invoice(llm_obj)
                    if llm_ok:
                        extracted_obj = llm_obj
                        numeric_ok = True
                        result.warnings = []
                    else:
                        result.warnings = val_warnings + [f"LLM also failed numeric: {llm_warn}"]

            if not llm_used:
                result.model_used = "deterministic_invoice_v2"

        numeric_ok, val_warnings = _validate_invoice(extracted_obj)
        if val_warnings:
            result.warnings = list(set(result.warnings or []) | set(val_warnings))

        result.extracted_obj = extracted_obj
        result.parsed_json = extracted_obj.model_dump()
        result.validation_errors = val_warnings
        result.numeric_validation_passed = numeric_ok
        result.success = True
        result.confidence = score_invoice_extraction(extracted_obj)
        return result

    def _call_llm_patch(self, prompt: str) -> Tuple[Optional[dict], str, int, Optional[str], Optional[str]]:
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
                return json.loads(content), model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"Invoice LLM patch call failed: {e}")
            return None, model_label, 0, None, str(e)

    def _call_llm_full(self, prompt: str) -> Tuple[Optional[InvoiceExtraction], str, int, Optional[str], Optional[str]]:
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
                obj = InvoiceExtraction.model_validate(json.loads(content))
                return obj, model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"Invoice LLM full call failed: {e}")
            return None, model_label, 0, None, str(e)

    @staticmethod
    def _merge_llm_patch(base: InvoiceExtraction, patch: dict, fields: List[str]) -> InvoiceExtraction:
        data = base.model_dump()
        for field in fields:
            if field in patch and patch[field] is not None:
                data[field] = patch[field]
        try:
            return InvoiceExtraction.model_validate(data)
        except Exception as e:
            logger.warning(f"Invoice: Failed to merge LLM patch: {e}")
            return base
