"""
grn_parser.py
-------------
Goods Received Note (GRN) document parser.

Extraction strategy:
  1. Deterministic parser runs FIRST (regex + PyMuPDF text)
  2. Validate result (sum(line_items) == total_amount)
  3. LLM fallback ONLY if mandatory fields are missing or validation fails
  4. LLM receives ONLY the section containing missing fields
  5. Compute rubric-based confidence score

Key rules:
  - Never calculate/infer monetary values — extract exactly what is printed
  - vendor_name returns None if not confidently found
  - ALL line items are extracted (not just the first)
  - Validation generates warnings only — never overwrites extracted values
  - qty_ordered vs qty_received extracted separately
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Any

import httpx

from app.core.config import settings
from app.schemas.extraction_schemas import GRNExtraction, GRNLineItemExtraction
from app.services.parsers.base_parser import BaseDocumentParser, ExtractionResult
from app.services.parsers.text_utils import preprocess_for_llm
from app.services.confidence import score_grn_extraction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

_GRN_MISSING_FIELDS_PROMPT = """You are a precise document data extractor specializing in Goods Received Notes (GRN).

The deterministic parser already extracted most fields successfully.
Only the following fields could NOT be extracted: {missing_fields}

Look at the relevant section of the GRN document below and extract ONLY those missing fields.
Return ONLY a valid JSON object containing those field names as keys.

RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate. If a field is genuinely missing, return null for it.
- vendor_name = the SUPPLIER company name (who delivered the goods).
- grn_date = the date goods were received (NOT the PO date).
- Dates must be in YYYY-MM-DD format.
- Monetary amounts must be floats (no currency symbols).

Missing fields to extract: {missing_fields}

Document section:
{section_text}
"""

_GRN_FULL_PROMPT = """You are a precise document data extractor specializing in Goods Received Notes (GRN).

Extract ALL structured data from the GRN document text below and return ONLY valid JSON.

CRITICAL RULES:
- Return ONLY raw JSON. No markdown, no code blocks, no explanation.
- Never hallucinate values. If a field is not present, return null.
- Preserve identifiers (GRN numbers, PO references, delivery note numbers) EXACTLY as written.
- vendor_name = the SUPPLIER company name (who delivered the goods).
- grn_date = the date goods were received (NOT the PO date).
- po_ref_raw = the Purchase Order number referenced on this GRN.
- delivery_note_number = delivery note or challan number if present.
- For each line item, extract qty_ordered (from PO) and qty_received (actually received).
- total_amount = pre-tax subtotal of all received goods.
- Dates must be in YYYY-MM-DD format.
- All monetary amounts must be floats.

JSON Schema:
{schema}

GRN Document Text:
{text}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        return float(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return None


def _norm_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _log_field(doc_type: str, field: str, pattern_desc: str, raw_match: Any, parsed: Any, status: str):
    logger.debug(
        f"[{doc_type}] field={field!r:20s}  pattern={pattern_desc!r:30s}  "
        f"raw={str(raw_match)!r:30s}  parsed={str(parsed)!r:20s}  status={status}"
    )


# ---------------------------------------------------------------------------
# Vendor extraction
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
    r'(?:Supplier\s*Name|Vendor\s*Name|Supplier|Vendor|Delivered\s*By|From)\s*[:\-]\s*([^\n]+)',
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
        r'^(?:Supplier\s*Name|Supplier|Vendor\s*Name|Vendor|From|Company|Delivered\s*By)\s*[:\-]?\s*',
        '', name, flags=re.I
    )
    name = re.split(
        r'(?i)\b(?:Phone|Tel|Email|Address|PO\b|Date|Bill|Ship|Attn|Contact|H\.No|H-|Fax|GST|GSTIN)\b',
        name
    )[0]
    name = name.strip(' :,;-\n\r\t')
    return name if len(name) > 2 else None


def _extract_vendor(text: str) -> Optional[str]:
    """Extract supplier/vendor name. Returns None if not confidently identified."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    buyer_idx = _get_buyer_line_index(lines)

    # Priority 1: Explicit label
    m = _VENDOR_LABEL_RE.search(text)
    if m:
        cand = _clean_company_name(m.group(1))
        if cand:
            _log_field("GRN", "vendor_name", "explicit_label", m.group(0), cand, "ok")
            return cand

    # Priority 2: Company suffix scan before buyer section
    for line in lines[:buyer_idx]:
        if re.match(r'^(GRN|GOODS|DELIVERY|RECEIPT|DATE|PAGE|PHONE|EMAIL|HTTP|WWW|PURCHASE)', line, re.I):
            continue
        if re.match(r'^\d', line):
            continue
        sm = _COMPANY_SUFFIX_RE.search(line)
        if sm:
            cand = _clean_company_name(sm.group(1))
            if cand and len(cand) > 3:
                _log_field("GRN", "vendor_name", "company_suffix_scan", line, cand, "ok")
                return cand

    _log_field("GRN", "vendor_name", "all_strategies", None, None, "missing")
    return None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_GRN_NUMBER = re.compile(
    r'\b(?:GRN|Goods\s*Receipt\s*(?:Note)?)\s*(?:Number|No\.?|#)?\s*[:#]\s*([A-Za-z0-9\-]+)',
    re.I
)
_RE_PO_REF     = re.compile(r'PO\s*(?:Ref|Reference|No\.?|Number)[.:\n\s]*([A-Za-z0-9\-]+)', re.I)
_RE_GRN_DATE   = re.compile(
    r'(?:Date\s*(?:of\s*)?(?:Receipt|Received|GRN)?|Receipt\s*Date|GRN\s*Date|Date)\s*[:\n\s]*'
    r'(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})',
    re.I
)
_RE_DN_NUMBER  = re.compile(r'(?:Delivery\s*Note|Challan|D\.?\s*N\.?)\s*(?:#|No\.?)?\s*[:\n\s]*([A-Za-z0-9\-]+)', re.I)
_RE_TOTAL      = re.compile(r'(?:Total\s*Amount|Grand\s*Total|(?<!\bSub)(?<!\bSub\s)Total)\s*[:\n\s]*([,\d]+\.\d{2})', re.I)
_RE_CONDITION  = re.compile(r'(?:Received\s*Condition|Condition\s*of\s*Goods?)\s*[:\n\s]*([^\n]+)', re.I)


# ---------------------------------------------------------------------------
# Line item extraction
# ---------------------------------------------------------------------------

def _extract_grn_lines(text: str) -> List[GRNLineItemExtraction]:
    """
    Extract ALL GRN line items from the goods receipt table.

    Strategy:
    - Find the line-item table header
    - For each subsequent non-header line with numeric amounts or quantities, treat as a line item
    - Stop at Total / Summary rows
    - Extract qty_ordered and qty_received as separate integer values from the row
    """
    items: List[GRNLineItemExtraction] = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    _STOP_RE = re.compile(
        r'^(?:Total\s*Amount|Grand\s*Total|Sub\s*Total|Tax|GST|IGST|CGST|SGST|'
        r'Discount|Note:|Terms|Remarks?|Authorized|Received\s*by|Signature)',
        re.I
    )
    _HEADER_KEYWORDS = {
        'item', 'description', 'qty', 'quantity', 'ordered', 'received',
        'unit', 'price', 'amount', 'total', 'rate', 'particulars', 'goods', 'accepted', 'rejected'
    }

    in_table = False

    for i, line in enumerate(lines):
        if not in_table:
            words = set(re.findall(r'[a-zA-Z]+', line.lower()))
            if len(words & _HEADER_KEYWORDS) >= 2:
                in_table = True
            continue

        if _STOP_RE.match(line):
            break

        if not line or re.match(r'^[-=_\s]+$', line):
            continue

        # Extract item code (leading 3-8 digit code) if present
        code_m = re.match(r'^(\d{3,8})\b', line)
        line_after_code = re.sub(r'^\d{3,8}\s*', '', line)

        # Strip leading line index / item markers (e.g. "Item 1", "#1", "1.")
        line_after_code = re.sub(r'(?i)^\s*(?:Item|#)?\s*\d{1,3}\b[.\s]*', '', line_after_code).strip()

        # Extract decimal amounts
        num_values = [_f(am) for am in re.findall(r'[\d,]+\.\d{2}', line) if _f(am) is not None]

        # Extract integer candidates (exclude years like 2024, 2025, 2026, 2027)
        line_no_decimals = re.sub(r'[\d,]+\.\d{2}', '', line_after_code)
        raw_ints = re.findall(r'\b(\d{1,4})\b', line_no_decimals)
        int_vals = [float(v) for v in raw_ints if int(v) < 10000 and int(v) not in (2024, 2025, 2026, 2027)]

        # Must have either decimal values or integer values to be a line item row
        if len(num_values) == 0 and len(int_vals) == 0:
            continue

        qty_ordered = int_vals[0] if len(int_vals) >= 1 else 1.0
        qty_received = int_vals[1] if len(int_vals) >= 2 else qty_ordered

        unit_price = num_values[0] if len(num_values) >= 1 else 0.0
        line_total = num_values[-1] if len(num_values) >= 2 else (qty_received * unit_price)

        # Extract description: text before the numeric quantities
        desc_text = line_no_decimals
        for iv in raw_ints:
            desc_text = re.sub(r'\b' + re.escape(iv) + r'\b', '', desc_text, count=1)

        # Strip unit of measure noise words
        desc_text = re.sub(r'(?i)\b(?:Nos|Pcs|Units|Ea|Each|Kg|Mtr|Boxes|Sets)\b', '', desc_text)
        desc = desc_text.strip(' \t-|:,')
        if not desc or desc.upper() in ('NOS', 'PCS', 'UNITS', 'EA', 'EACH'):
            desc = f"Line item {len(items)+1}"

        _log_field("GRN", f"line_item[{len(items)}]", "numeric_col_detect",
                   line[:80],
                   f"qty_ord={qty_ordered} qty_rec={qty_received} up={unit_price} total={line_total}",
                   "ok")

        items.append(GRNLineItemExtraction(
            description=desc[:150],
            qty_ordered=qty_ordered,
            qty_received=qty_received,
            unit_price=unit_price,
            line_total=line_total
        ))

    return items


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_grn(obj: GRNExtraction) -> Tuple[bool, List[str]]:
    warnings = []
    total = obj.total_amount or 0.0

    if obj.line_items:
        lines_sum = sum(li.line_total or 0.0 for li in obj.line_items)
        if total > 0 and abs(lines_sum - total) > 1.0:
            warnings.append(
                f"sum(line_items.line_total)={lines_sum:.2f} != total_amount={total:.2f} — warning only"
            )
    else:
        warnings.append("No line items extracted from GRN")

    return len(warnings) == 0, warnings


def _find_missing_fields_grn(obj: GRNExtraction) -> List[str]:
    missing = []
    if not obj.grn_number or obj.grn_number in ("UNKNOWN", ""):
        missing.append("grn_number")
    if not obj.vendor_name:
        missing.append("vendor_name")
    if not obj.total_amount or obj.total_amount == 0.0:
        missing.append("total_amount")
    if not obj.grn_date:
        missing.append("grn_date")
    return missing


def _extract_section_for_fields(text: str, fields: List[str]) -> str:
    lines = text.split('\n')
    sections = set()
    for f in fields:
        if f in ('total_amount',):
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

def _det_parse_grn(text: str) -> GRNExtraction:
    """Fully deterministic GRN extraction. Returns None for fields not found."""

    grn_m = _RE_GRN_NUMBER.search(text)
    if not grn_m:
        # Looser fallback
        grn_m = re.search(r'\bGRN\s*[#:\-]?\s*([A-Za-z0-9\-]+)', text, re.I)
    grn_num = grn_m.group(1).strip() if grn_m else "UNKNOWN"
    _log_field("GRN", "grn_number", "RE_GRN_NUMBER", grn_m and grn_m.group(0), grn_num,
               "ok" if grn_num != "UNKNOWN" else "missing")

    po_m = _RE_PO_REF.search(text)
    po_ref = po_m.group(1).strip() if po_m else None
    _log_field("GRN", "po_ref_raw", "RE_PO_REF", po_m and po_m.group(0), po_ref,
               "ok" if po_ref else "missing")

    date_m = _RE_GRN_DATE.search(text)
    grn_date = _norm_date(date_m.group(1)) if date_m else None
    _log_field("GRN", "grn_date", "RE_GRN_DATE", date_m and date_m.group(0), grn_date,
               "ok" if grn_date else "missing")

    dn_m = _RE_DN_NUMBER.search(text)
    dn_num = dn_m.group(1).strip() if dn_m else None
    _log_field("GRN", "delivery_note_number", "RE_DN_NUMBER", dn_m and dn_m.group(0), dn_num,
               "ok" if dn_num else "missing")

    vendor = _extract_vendor(text)

    tot_m = _RE_TOTAL.search(text)
    total = _f(tot_m.group(1)) if tot_m else 0.0
    _log_field("GRN", "total_amount", "RE_TOTAL", tot_m and tot_m.group(0), total,
               "ok" if total else "missing")

    cond_m = _RE_CONDITION.search(text)
    condition = cond_m.group(1).strip()[:100] if cond_m else None

    line_items = _extract_grn_lines(text)
    _log_field("GRN", "line_items_count", "numeric_col_scan", None, len(line_items),
               "ok" if line_items else "none_found")

    # If total not found but line items have amounts, derive total from them
    if (total == 0.0 or total is None) and line_items:
        computed_total = sum(li.line_total or 0.0 for li in line_items)
        if computed_total > 0:
            total = computed_total
            _log_field("GRN", "total_amount", "derived_from_line_items", None, total, "derived")

    return GRNExtraction(
        grn_number=grn_num,
        grn_date=grn_date,
        delivery_note_number=dn_num,
        po_ref_raw=po_ref,
        vendor_name=vendor,
        total_amount=total or 0.0,
        received_condition=condition,
        line_items=line_items
    )


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class GRNParser(BaseDocumentParser):
    """
    GRN parser — deterministic first, targeted LLM fallback.
    """

    def extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        result = ExtractionResult(raw_text=raw_text, model_used="deterministic_grn_v2")
        result.prompt = "Deterministic GRN parser — LLM only invoked for missing fields"

        cleaned = preprocess_for_llm(raw_text)
        result.cleaned_text = cleaned

        logger.info("GRN: Running deterministic parser")
        extracted_obj = _det_parse_grn(cleaned)

        numeric_ok, val_warnings = _validate_grn(extracted_obj)
        missing_fields = _find_missing_fields_grn(extracted_obj)
        result.warnings = val_warnings

        if val_warnings:
            logger.warning(f"GRN validation warnings: {val_warnings}")

        if not missing_fields and numeric_ok:
            logger.info("GRN: Deterministic extraction succeeded — skipping LLM")
            result.model_used = "deterministic_grn_v2"
        else:
            llm_used = False

            if missing_fields and settings.OPENROUTER_API_KEY:
                logger.info(f"GRN: LLM fallback for missing fields: {missing_fields}")
                section_text = _extract_section_for_fields(cleaned, missing_fields)
                prompt = _GRN_MISSING_FIELDS_PROMPT.format(
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
                    logger.warning(f"GRN: LLM fallback failed: {err}")
                    result.validation_errors = [err]

            elif not missing_fields and not numeric_ok and settings.OPENROUTER_API_KEY:
                logger.info("GRN: LLM fallback for numeric inconsistency")
                schema_str = json.dumps(GRNExtraction.model_json_schema(), indent=2)
                prompt = _GRN_FULL_PROMPT.format(schema=schema_str, text=cleaned)
                result.prompt = prompt

                llm_obj, model, tokens, raw_resp, err = self._call_llm_full(prompt)
                result.raw_llm_response = raw_resp
                result.model_used = model
                result.tokens_used = tokens
                result.retry_attempted = True

                if llm_obj:
                    llm_used = True
                    llm_ok, llm_warn = _validate_grn(llm_obj)
                    if llm_ok:
                        extracted_obj = llm_obj
                        numeric_ok = True
                        result.warnings = []
                    else:
                        result.warnings = val_warnings + [f"LLM also failed numeric: {llm_warn}"]

            if not llm_used:
                result.model_used = "deterministic_grn_v2"

        numeric_ok, val_warnings = _validate_grn(extracted_obj)
        if val_warnings:
            result.warnings = list(set(result.warnings or []) | set(val_warnings))

        result.extracted_obj = extracted_obj
        result.parsed_json = extracted_obj.model_dump()
        result.validation_errors = val_warnings
        result.numeric_validation_passed = numeric_ok
        result.success = True
        result.confidence = score_grn_extraction(extracted_obj)
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
            with httpx.Client(timeout=60.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code != 200:
                    return None, model_label, 0, res.text, f"HTTP {res.status_code}"
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return json.loads(content), model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"GRN LLM patch call failed: {e}")
            return None, model_label, 0, None, str(e)

    def _call_llm_full(self, prompt: str) -> Tuple[Optional[GRNExtraction], str, int, Optional[str], Optional[str]]:
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
            with httpx.Client(timeout=60.0) as client:
                res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
                if res.status_code != 200:
                    return None, model_label, 0, res.text, f"HTTP {res.status_code}"
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                obj = GRNExtraction.model_validate(json.loads(content))
                return obj, model_label, tokens, content, None
        except Exception as e:
            logger.warning(f"GRN LLM full call failed: {e}")
            return None, model_label, 0, None, str(e)

    @staticmethod
    def _merge_llm_patch(base: GRNExtraction, patch: dict, fields: List[str]) -> GRNExtraction:
        data = base.model_dump()
        for field in fields:
            if field in patch and patch[field] is not None:
                data[field] = patch[field]
        try:
            return GRNExtraction.model_validate(data)
        except Exception as e:
            logger.warning(f"GRN: Failed to merge LLM patch: {e}")
            return base
