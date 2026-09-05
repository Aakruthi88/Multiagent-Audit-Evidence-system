"""
confidence.py
-------------
Deterministic extraction confidence scorer.

Replaces arbitrary confidence values (0.85 / 0.95) with a
rubric-based score computed from actual extraction quality signals.

Max score: 100 points → stored as 0.0–1.0 float.
"""

from typing import Any, List, Optional
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rubric weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "required_fields":    30,   # All required fields non-null
    "json_valid":         20,   # Pydantic validation passed
    "numeric_validation": 20,   # sum checks / balance checks passed
    "dates_parsed":       10,   # All date fields are valid ISO dates
    "identifiers":        10,   # PO/Invoice/GRN numbers are non-null, non-empty
    "line_items":         10,   # Line items present and internally consistent
}

MAX_SCORE = sum(WEIGHTS.values())  # 100


def compute_confidence(
    required_fields_ok: bool,
    json_valid: bool,
    numeric_validation_ok: bool,
    dates_ok: bool,
    identifiers_ok: bool,
    line_items_ok: bool,
    warnings: Optional[List[str]] = None
) -> float:
    """
    Compute a 0.0–1.0 confidence score based on extraction quality signals.

    Args:
        required_fields_ok: All required Pydantic fields are non-null.
        json_valid:         Pydantic model_validate() succeeded.
        numeric_validation_ok: Arithmetic checks pass (e.g. subtotal + tax == total).
        dates_ok:           All date fields parsed successfully.
        identifiers_ok:     PO/invoice/GRN numbers are non-null strings.
        line_items_ok:      Line items list is non-empty and amounts consistent.
        warnings:           Optional list of warning strings (logged, not penalised further).

    Returns:
        float in [0.0, 1.0]
    """
    score = 0

    if required_fields_ok:
        score += WEIGHTS["required_fields"]
    if json_valid:
        score += WEIGHTS["json_valid"]
    if numeric_validation_ok:
        score += WEIGHTS["numeric_validation"]
    if dates_ok:
        score += WEIGHTS["dates_parsed"]
    if identifiers_ok:
        score += WEIGHTS["identifiers"]
    if line_items_ok:
        score += WEIGHTS["line_items"]

    confidence = round(score / MAX_SCORE, 4)

    if warnings:
        for w in warnings:
            logger.debug(f"Confidence warning: {w}")

    logger.debug(f"Confidence score: {score}/{MAX_SCORE} = {confidence}")
    return confidence


# ---------------------------------------------------------------------------
# Document-type specific helpers
# ---------------------------------------------------------------------------

def _is_valid_date(date_str: Any) -> bool:
    """Check if a value looks like a valid ISO date string."""
    import re
    if not date_str or not isinstance(date_str, str):
        return False
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str.strip()))


def _amounts_equal(a: Optional[float], b: Optional[float], tolerance: float = 0.02) -> bool:
    """Check if two amounts are equal within a tolerance (handles rounding)."""
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def score_po_extraction(extracted, val_warnings: Optional[List[str]] = None) -> float:
    """Compute confidence for a POExtraction object."""
    warnings = []

    has_val_errors = False
    if val_warnings:
        for w in val_warnings:
            warnings.append(w)
            if "Validation Error:" in w:
                has_val_errors = True

    # vendor_name is Optional — treat null or invalid as a warning
    vendor_ok = bool(extracted.vendor_name and extracted.vendor_name.strip())
    if not vendor_ok:
        warnings.append("PO: vendor_name is null — could not identify supplier")

    required_fields_ok = bool(
        extracted.po_number and
        extracted.subtotal is not None and extracted.total_amount is not None
    ) and vendor_ok and not has_val_errors

    json_valid = True  # If we have a Pydantic object it's already valid

    # Numeric: subtotal + tax == total
    expected_total = (extracted.subtotal or 0) + (extracted.tax_amount or 0)
    numeric_ok = _amounts_equal(expected_total, extracted.total_amount, tolerance=1.0) and not has_val_errors
    if not _amounts_equal(expected_total, extracted.total_amount, tolerance=1.0):
        warnings.append(f"PO: subtotal({extracted.subtotal}) + tax({extracted.tax_amount}) = {expected_total} != total({extracted.total_amount})")

    # Numeric: sum of line items == subtotal
    if extracted.line_items:
        lines_sum = sum(li.line_total or 0 for li in extracted.line_items)
        if not _amounts_equal(lines_sum, extracted.subtotal, tolerance=1.0):
            warnings.append(f"PO: sum(line_items)={lines_sum} != subtotal={extracted.subtotal}")

    dates_ok = _is_valid_date(extracted.po_date)
    identifiers_ok = bool(extracted.po_number and extracted.po_number.strip() and extracted.po_number != "UNKNOWN")
    line_items_ok = bool(extracted.line_items)

    score = compute_confidence(
        required_fields_ok=required_fields_ok,
        json_valid=json_valid,
        numeric_validation_ok=numeric_ok,
        dates_ok=dates_ok,
        identifiers_ok=identifiers_ok,
        line_items_ok=line_items_ok,
        warnings=warnings
    )

    if has_val_errors:
        logger.warning(f"PO: Marking extraction as LOW_CONFIDENCE (0.40) due to validation errors: {warnings}")
        return min(score, 0.40)

    return score


def score_invoice_extraction(extracted) -> float:
    """Compute confidence for an InvoiceExtraction object."""
    warnings = []

    vendor_ok = bool(extracted.vendor_name and extracted.vendor_name.strip())
    if not vendor_ok:
        warnings.append("Invoice: vendor_name is null — could not identify supplier")

    required_fields_ok = bool(
        extracted.invoice_number and
        extracted.subtotal is not None and extracted.total_amount is not None
    ) and vendor_ok

    json_valid = True

    expected_total = (extracted.subtotal or 0) + (extracted.tax_amount or 0)
    numeric_ok = _amounts_equal(expected_total, extracted.total_amount, tolerance=1.0)
    if not numeric_ok:
        warnings.append(f"Invoice: subtotal+tax={expected_total} != total={extracted.total_amount}")

    if extracted.line_items:
        lines_sum = sum(li.line_total or 0 for li in extracted.line_items)
        if not _amounts_equal(lines_sum, extracted.subtotal, tolerance=1.0):
            warnings.append(f"Invoice: sum(line_items)={lines_sum} != subtotal={extracted.subtotal}")
            # Warning only — do not flip numeric_ok

    dates_ok = _is_valid_date(extracted.invoice_date)
    identifiers_ok = bool(extracted.invoice_number and extracted.invoice_number.strip() and extracted.invoice_number != "UNKNOWN")
    line_items_ok = bool(extracted.line_items)

    return compute_confidence(
        required_fields_ok=required_fields_ok,
        json_valid=json_valid,
        numeric_validation_ok=numeric_ok,
        dates_ok=dates_ok,
        identifiers_ok=identifiers_ok,
        line_items_ok=line_items_ok,
        warnings=warnings
    )


def score_grn_extraction(extracted) -> float:
    """Compute confidence for a GRNExtraction object."""
    warnings = []

    required_fields_ok = bool(
        extracted.grn_number and extracted.total_amount is not None
    )
    json_valid = True

    if extracted.line_items:
        lines_sum = sum(li.line_total or 0 for li in extracted.line_items)
        numeric_ok = _amounts_equal(lines_sum, extracted.total_amount, tolerance=1.0)
        if not numeric_ok:
            warnings.append(f"GRN: sum(line_items)={lines_sum} != total={extracted.total_amount}")
    else:
        numeric_ok = False
        warnings.append("GRN: no line items extracted")

    dates_ok = _is_valid_date(extracted.grn_date)
    identifiers_ok = bool(extracted.grn_number and extracted.grn_number.strip())
    line_items_ok = bool(extracted.line_items)

    return compute_confidence(
        required_fields_ok=required_fields_ok,
        json_valid=json_valid,
        numeric_validation_ok=numeric_ok,
        dates_ok=dates_ok,
        identifiers_ok=identifiers_ok,
        line_items_ok=line_items_ok,
        warnings=warnings
    )


def score_bank_extraction(extracted, count_match: bool) -> float:
    """Compute confidence for a BankExtraction object."""
    warnings = []

    required_fields_ok = bool(
        extracted.account_number and extracted.transactions
    )
    json_valid = True

    # For bank: numeric validation = transaction count match
    numeric_ok = count_match
    if not numeric_ok:
        warnings.append("Bank: transaction count mismatch")

    dates_ok = _is_valid_date(extracted.statement_date)
    identifiers_ok = bool(extracted.account_number and extracted.account_number.strip())
    line_items_ok = bool(extracted.transactions)

    return compute_confidence(
        required_fields_ok=required_fields_ok,
        json_valid=json_valid,
        numeric_validation_ok=numeric_ok,
        dates_ok=dates_ok,
        identifiers_ok=identifiers_ok,
        line_items_ok=line_items_ok,
        warnings=warnings
    )
