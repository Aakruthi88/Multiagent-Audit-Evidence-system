import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from app.core.logging import logger
from app.models.models import (
    AuditBundle, Document, PurchaseOrder, POLineItem,
    Invoice, InvoiceLineItem, GRN, GRNLineItem,
    BankStatement, BankTransaction, Vendor,
    VerificationRun, VerificationCheck, Discrepancy
)

RULES_VERSION = "1.0"
SEVERITY_WEIGHTS = {"critical": 40, "high": 20, "medium": 10, "low": 5}

# ── helpers ────────────────────────────────────────────────────────────────────

def _d(val) -> Decimal:
    if val is None:
        return Decimal("0.00")
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _tolerance(reference: Decimal, pct: float = 0.001, min_amount: Decimal = Decimal("1.00")) -> Decimal:
    return max(min_amount, (reference * Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _normalize_po_number(raw: str) -> str:
    """Uppercase, strip whitespace & leading zeros for canonical matching."""
    if not raw:
        return ""
    return re.sub(r'\s+', '', raw).upper().lstrip("0")

def _check(run_id, check_type: str, status: str, expected=None, actual=None, variance=None, severity=None, explanation="") -> VerificationCheck:
    return VerificationCheck(
        run_id=run_id,
        check_type=check_type,
        status=status,
        expected_value=str(expected) if expected is not None else None,
        actual_value=str(actual) if actual is not None else None,
        variance=variance,
        severity=severity,
        explanation=explanation
    )

def _discrepancy(run_id, check_id, category: str, severity: str, description: str, recommended_action: str = "") -> Discrepancy:
    return Discrepancy(
        run_id=run_id,
        check_id=check_id,
        category=category,
        severity=severity,
        description=description,
        recommended_action=recommended_action
    )

# ── Main Service ───────────────────────────────────────────────────────────────

class VerificationService:

    def run_all_checks(self, db: Session, bundle: AuditBundle) -> VerificationRun:
        """
        Executes all deterministic verification rules (Sections 6.1–6.6)
        against a single audit bundle. All numbers are computed in Python;
        the LLM is never called from here.
        """
        bundle_id = bundle.bundle_id
        logger.info(f"[Verification Service] Starting verification for bundle {bundle_id}")

        # Create verification run record
        run = VerificationRun(
            bundle_id=bundle_id,
            rules_version=RULES_VERSION
        )
        db.add(run)
        db.flush()
        run_id = run.run_id

        checks: List[VerificationCheck] = []
        discrepancies: List[Discrepancy] = []

        # Fetch evidence rows
        po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle_id).first()
        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle_id).first()
        grn = db.query(GRN).filter(GRN.bundle_id == bundle_id).first()
        bs = db.query(BankStatement).filter(BankStatement.bundle_id == bundle_id).first()

        # ── 6.1 Document Completeness ──────────────────────────────────────────
        missing = []
        for doc_type, record in [("purchase_order", po), ("invoice", inv), ("grn", grn), ("bank_statement", bs)]:
            if record is None:
                missing.append(doc_type)
                c = _check(run_id, f"doc_completeness_{doc_type}", "fail",
                           expected="present", actual="missing",
                           severity="high" if doc_type != "grn" else "critical",
                           explanation=f"{doc_type} not provided — cannot complete 4-way match")
                db.add(c); db.flush()
                checks.append(c)
                d = _discrepancy(run_id, c.check_id, "missing_document",
                                 "high" if doc_type != "grn" else "critical",
                                 f"{doc_type} not provided — cannot complete 4-way match",
                                 f"Obtain and upload the missing {doc_type} document.")
                db.add(d); discrepancies.append(d)
            else:
                c = _check(run_id, f"doc_completeness_{doc_type}", "pass",
                           expected="present", actual="present",
                           explanation=f"{doc_type} present")
                db.add(c); checks.append(c)

        # ── 6.2 PO ↔ Invoice ──────────────────────────────────────────────────
        if po and inv:
            # PO reference match
            inv_po_ref = _normalize_po_number(inv.po_ref_raw or "")
            po_num_norm = _normalize_po_number(po.po_number or "")
            if inv_po_ref == po_num_norm:
                c = _check(run_id, "po_invoice_ref_match", "pass",
                           expected=po_num_norm, actual=inv_po_ref,
                           explanation="Invoice PO reference matches PO number")
                db.add(c); checks.append(c)
            else:
                c = _check(run_id, "po_invoice_ref_match", "fail",
                           expected=po_num_norm, actual=inv_po_ref,
                           severity="critical",
                           explanation=f"Invoice references PO '{inv_po_ref}' but bundle PO is '{po_num_norm}' — wrong transaction")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "po_reference_mismatch", "critical",
                                 f"Invoice PO reference '{inv_po_ref}' does not match PO number '{po_num_norm}'.",
                                 "Verify the correct PO is attached to this invoice.")
                db.add(d); discrepancies.append(d)

            # Vendor fuzzy match
            po_vendor = po.vendor.name_raw if po.vendor else ""
            inv_vendor = inv.vendor.name_raw if inv.vendor else ""
            score = float(fuzz.token_sort_ratio(po_vendor.lower(), inv_vendor.lower()))
            if score >= 90:
                vendor_status, vendor_severity = "pass", None
            elif score >= 70:
                vendor_status, vendor_severity = "warning", "medium"
            else:
                vendor_status, vendor_severity = "fail", "high"

            c = _check(run_id, "po_invoice_vendor_match", vendor_status,
                       expected=po_vendor, actual=inv_vendor,
                       variance=Decimal(str(round(100 - score, 2))),
                       severity=vendor_severity,
                       explanation=f"Vendor name similarity score: {score:.1f}%")
            db.add(c); db.flush(); checks.append(c)

            if vendor_status in ("warning", "fail"):
                d = _discrepancy(run_id, c.check_id, "vendor_mismatch", vendor_severity,
                                 f"Vendor name on invoice '{inv_vendor}' vs PO '{po_vendor}' — similarity {score:.1f}%.",
                                 "Confirm vendor identity manually or via vendor master.")
                db.add(d); discrepancies.append(d)

            # Amount comparison: PO total vs Invoice total
            po_total = _d(po.total_amount)
            inv_total = _d(inv.total_amount)
            tol = _tolerance(po_total)
            variance = abs(po_total - inv_total)
            if variance <= tol:
                c = _check(run_id, "po_invoice_total_match", "pass",
                           expected=po_total, actual=inv_total,
                           variance=variance, explanation="PO and Invoice totals match within tolerance")
                db.add(c); checks.append(c)
            else:
                variance_pct = (variance / po_total * 100).quantize(Decimal("0.01")) if po_total else Decimal("0")
                c = _check(run_id, "po_invoice_total_match", "fail",
                           expected=po_total, actual=inv_total,
                           variance=variance, severity="critical",
                           explanation=f"Invoice total ₹{inv_total} vs PO total ₹{po_total} — variance ₹{variance} ({variance_pct}%). "
                                       f"This flags an overbill/underbill with no corresponding PO amendment on file.")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "amount_mismatch", "critical",
                                 f"Invoice total ₹{inv_total} exceeds PO total ₹{po_total} by ₹{variance} ({variance_pct}%).",
                                 "Obtain an approved PO amendment or request a credit note from the vendor.")
                db.add(d); discrepancies.append(d)

            # Tax rate consistency
            po_tax_rate = _d(po.tax_rate)
            inv_tax_rate = _d(inv.tax_rate)
            if po_tax_rate == inv_tax_rate:
                c = _check(run_id, "tax_rate_consistency", "pass",
                           expected=po_tax_rate, actual=inv_tax_rate,
                           explanation="Tax rates match between PO and Invoice")
                db.add(c); checks.append(c)
            else:
                c = _check(run_id, "tax_rate_consistency", "warning",
                           expected=po_tax_rate, actual=inv_tax_rate,
                           severity="medium",
                           explanation=f"PO tax rate {po_tax_rate}% ≠ Invoice tax rate {inv_tax_rate}%")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "tax_rate_mismatch", "medium",
                                 f"Tax rate on PO ({po_tax_rate}%) differs from invoice ({inv_tax_rate}%).",
                                 "Verify applicable tax rate with tax compliance team.")
                db.add(d); discrepancies.append(d)

            # Internal arithmetic check on invoice: verify subtotal + tax == total
            # Use stored inv.subtotal (authoritative from parser) rather than sum(line_items)
            # because duplicate line items from multi-pass parsing would inflate the sum.
            inv_subtotal = _d(inv.subtotal)
            inv_tax = _d(inv.tax_amount)
            inv_total = _d(inv.total_amount)
            if inv_subtotal > Decimal("0"):
                expected_total = (inv_subtotal + inv_tax).quantize(Decimal("0.01"))
                if abs(expected_total - inv_total) <= Decimal("1.00"):
                    c = _check(run_id, "invoice_arithmetic_check", "pass",
                               expected=expected_total, actual=inv_total,
                               explanation="Invoice arithmetic is internally consistent (subtotal + tax = total)")
                    db.add(c); checks.append(c)
                else:
                    c = _check(run_id, "invoice_arithmetic_check", "fail",
                               expected=expected_total, actual=inv_total,
                               variance=abs(expected_total - inv_total),
                               severity="high",
                               explanation=f"Invoice subtotal+tax={expected_total} ≠ stated total={inv_total}")
                    db.add(c); db.flush(); checks.append(c)
                    d = _discrepancy(run_id, c.check_id, "amount_mismatch", "high",
                                     "Invoice stated total does not equal subtotal + tax amount.",
                                     "Request a corrected invoice from the vendor.")
                    db.add(d); discrepancies.append(d)
        else:
            for check_type in ["po_invoice_ref_match", "po_invoice_vendor_match",
                               "po_invoice_total_match", "tax_rate_consistency", "invoice_arithmetic_check"]:
                c = _check(run_id, check_type, "not_applicable",
                           explanation="Skipped — PO or Invoice missing")
                db.add(c); checks.append(c)

        # ── 6.3 PO ↔ GRN ─────────────────────────────────────────────────────
        # CRITICAL: GRN total is PRE-TAX; compare against PO.subtotal, NOT PO.total_amount
        if po and grn:
            po_sub = _d(po.subtotal)
            grn_total = _d(grn.total_amount)
            tol = _tolerance(po_sub)
            variance = abs(grn_total - po_sub)
            if variance <= tol:
                c = _check(run_id, "po_grn_amount_match", "pass",
                           expected=po_sub, actual=grn_total,
                           variance=variance,
                           explanation="GRN total matches PO pre-tax subtotal (GRNs are always pre-tax in this dataset)")
                db.add(c); checks.append(c)
            else:
                c = _check(run_id, "po_grn_amount_match", "fail",
                           expected=po_sub, actual=grn_total,
                           variance=variance, severity="high",
                           explanation=f"GRN pre-tax total ₹{grn_total} vs PO subtotal ₹{po_sub} — variance ₹{variance}. "
                                       f"Note: GRN.total_amount is intentionally compared to PO.subtotal (not PO.total_amount).")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "amount_mismatch", "high",
                                 f"GRN total ₹{grn_total} does not match PO pre-tax subtotal ₹{po_sub}.",
                                 "Confirm received quantity and unit prices with the supplier.")
                db.add(d); discrepancies.append(d)

            # GRN line quantity vs PO line quantity
            po_lines = db.query(POLineItem).filter(POLineItem.po_id == po.po_id).all()
            grn_lines = db.query(GRNLineItem).filter(GRNLineItem.grn_id == grn.grn_id).all()
            for gl in grn_lines:
                matching_pl = next((pl for pl in po_lines if pl.description.lower()[:20] in gl.description.lower()), None)
                if matching_pl and gl.qty_ordered is not None and gl.qty_received is not None:
                    qty_ordered = _d(gl.qty_ordered)
                    qty_received = _d(gl.qty_received)
                    if qty_received < qty_ordered:
                        shortfall = qty_ordered - qty_received
                        c = _check(run_id, "grn_qty_short_shipment", "warning",
                                   expected=qty_ordered, actual=qty_received,
                                   variance=shortfall, severity="medium",
                                   explanation=f"Short shipment on '{gl.description}': ordered {qty_ordered}, received {qty_received}")
                        db.add(c); db.flush(); checks.append(c)
                        d = _discrepancy(run_id, c.check_id, "qty_mismatch", "medium",
                                         f"Short shipment: {shortfall} units of '{gl.description}' not received.",
                                         "Chase outstanding delivery or reject partial invoice payment.")
                        db.add(d); discrepancies.append(d)
                    elif qty_received > qty_ordered:
                        excess = qty_received - qty_ordered
                        c = _check(run_id, "grn_qty_over_delivery", "warning",
                                   expected=qty_ordered, actual=qty_received,
                                   variance=excess, severity="medium",
                                   explanation=f"Over-delivery on '{gl.description}': ordered {qty_ordered}, received {qty_received}")
                        db.add(c); db.flush(); checks.append(c)
                        d = _discrepancy(run_id, c.check_id, "qty_mismatch", "medium",
                                         f"Over-delivery: {excess} excess units of '{gl.description}' received without PO authorisation.",
                                         "Return excess goods or obtain a PO amendment.")
                        db.add(d); discrepancies.append(d)
                    elif qty_received == Decimal("0"):
                        c = _check(run_id, "grn_qty_zero_received", "fail",
                                   expected=qty_ordered, actual=Decimal("0"),
                                   variance=qty_ordered, severity="critical",
                                   explanation=f"Zero goods received for '{gl.description}' — invoice must not be paid")
                        db.add(c); db.flush(); checks.append(c)
                        d = _discrepancy(run_id, c.check_id, "qty_mismatch", "critical",
                                         f"No goods received for '{gl.description}' — invoice should not be approved for payment.",
                                         "Block payment and investigate with procurement team.")
                        db.add(d); discrepancies.append(d)
                    else:
                        c = _check(run_id, "grn_qty_match", "pass",
                                   expected=qty_ordered, actual=qty_received,
                                   explanation=f"Quantities match for '{gl.description}'")
                        db.add(c); checks.append(c)
        else:
            for check_type in ["po_grn_amount_match", "grn_qty_match"]:
                c = _check(run_id, check_type, "not_applicable",
                           explanation="Skipped — PO or GRN missing")
                db.add(c); checks.append(c)

        # ── 6.4 Invoice ↔ GRN ─────────────────────────────────────────────────
        if inv and grn:
            inv_sub = _d(inv.subtotal)
            grn_total = _d(grn.total_amount)
            tol = _tolerance(inv_sub)
            variance = abs(inv_sub - grn_total)
            if variance <= tol:
                c = _check(run_id, "invoice_grn_amount_match", "pass",
                           expected=inv_sub, actual=grn_total,
                           variance=variance,
                           explanation="Invoice subtotal matches GRN pre-tax total")
                db.add(c); checks.append(c)
            else:
                c = _check(run_id, "invoice_grn_amount_match", "fail",
                           expected=inv_sub, actual=grn_total,
                           variance=variance, severity="high",
                           explanation=f"Invoice subtotal ₹{inv_sub} ≠ GRN total ₹{grn_total} — paying for unconfirmed goods")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "amount_mismatch", "high",
                                 f"Invoice billed ₹{inv_sub} but GRN only confirms ₹{grn_total}.",
                                 "Reconcile with GRN before approving payment.")
                db.add(d); discrepancies.append(d)
        elif inv and not grn:
            c = _check(run_id, "invoice_grn_amount_match", "not_applicable",
                       severity="critical",
                       explanation="GRN missing — cannot verify goods receipt against invoice; escalating to critical")
            db.add(c); db.flush(); checks.append(c)
            d = _discrepancy(run_id, c.check_id, "missing_document", "critical",
                             "GRN missing — goods-receipt protection for invoice cannot be exercised.",
                             "Do not approve payment until GRN is obtained and verified.")
            db.add(d); discrepancies.append(d)
        else:
            c = _check(run_id, "invoice_grn_amount_match", "not_applicable",
                       explanation="Skipped — Invoice or GRN missing")
            db.add(c); checks.append(c)

        # ── 6.5 Invoice ↔ Bank Statement ──────────────────────────────────────
        if inv and bs:
            bank_txns = db.query(BankTransaction).filter(BankTransaction.statement_id == bs.statement_id).all()
            matched_txn: Optional[BankTransaction] = None

            # Try to match by extracted_invoice_number
            inv_num_clean = re.sub(r'[^0-9a-zA-Z]', '', inv.invoice_number or "").upper()
            for txn in bank_txns:
                txn_inv = re.sub(r'[^0-9a-zA-Z]', '', txn.extracted_invoice_number or "").upper()
                if txn_inv and txn_inv in inv_num_clean or inv_num_clean in txn_inv:
                    matched_txn = txn
                    break

            if matched_txn:
                # Amount check
                debit = _d(matched_txn.debit_amount)
                inv_total = _d(inv.total_amount)
                variance = abs(debit - inv_total)
                if variance <= Decimal("1.00"):
                    c = _check(run_id, "payment_amount_match", "pass",
                               expected=inv_total, actual=debit,
                               variance=variance,
                               explanation=f"Bank debit ₹{debit} matches invoice total ₹{inv_total}")
                    db.add(c); checks.append(c)
                else:
                    c = _check(run_id, "payment_amount_match", "fail",
                               expected=inv_total, actual=debit,
                               variance=variance, severity="high",
                               explanation=f"Bank debit ₹{debit} ≠ Invoice total ₹{inv_total}")
                    db.add(c); db.flush(); checks.append(c)
                    d = _discrepancy(run_id, c.check_id, "amount_mismatch", "high",
                                     f"Payment of ₹{debit} does not equal invoice total ₹{inv_total}.",
                                     "Investigate partial payment or overpayment with treasury.")
                    db.add(d); discrepancies.append(d)

                # Chronology: payment must NOT precede invoice date
                if inv.invoice_date and matched_txn.txn_date:
                    txn_date: date = matched_txn.txn_date
                    inv_date: date = inv.invoice_date
                    if txn_date < inv_date:
                        c = _check(run_id, "payment_before_invoice_date", "fail",
                                   expected=f">= {inv_date}", actual=str(txn_date),
                                   severity="high",
                                   explanation=f"Payment date {txn_date} precedes invoice date {inv_date} — "
                                               f"possible backdated invoice, advance payment without authorisation, or extraction error")
                        db.add(c); db.flush(); checks.append(c)
                        d = _discrepancy(run_id, c.check_id, "date_sequence", "high",
                                         f"Payment recorded {txn_date} before invoice date {inv_date}.",
                                         "Verify for backdated invoice, advance payment authorisation, or extraction date error.")
                        db.add(d); discrepancies.append(d)
                    else:
                        c = _check(run_id, "payment_before_invoice_date", "pass",
                                   expected=f">= {inv_date}", actual=str(txn_date),
                                   explanation="Payment date is on or after invoice date")
                        db.add(c); checks.append(c)

                # Chronology: payment must NOT precede GRN date
                if grn and grn.grn_date and matched_txn.txn_date:
                    txn_date: date = matched_txn.txn_date
                    grn_date: date = grn.grn_date
                    if txn_date < grn_date:
                        c = _check(run_id, "payment_before_grn_date", "fail",
                                   expected=f">= {grn_date}", actual=str(txn_date),
                                   severity="high",
                                   explanation=f"Payment {txn_date} before goods receipt confirmed {grn_date}")
                        db.add(c); db.flush(); checks.append(c)
                        d = _discrepancy(run_id, c.check_id, "date_sequence", "high",
                                         f"Payment recorded {txn_date} before goods receipt confirmed on {grn_date}.",
                                         "Verify payment authorisation preceded goods receipt is acceptable per policy.")
                        db.add(d); discrepancies.append(d)
                    else:
                        c = _check(run_id, "payment_before_grn_date", "pass",
                                   expected=f">= {grn_date}", actual=str(txn_date),
                                   explanation="Payment date is on or after GRN date")
                        db.add(c); checks.append(c)

                # Mark transaction matched
                matched_txn.matched_invoice_id = inv.invoice_id
                db.add(matched_txn)
            else:
                c = _check(run_id, "payment_matched_to_invoice", "fail",
                           expected=inv.invoice_number, actual="no match",
                           severity="high",
                           explanation=f"No bank transaction narration matches invoice {inv.invoice_number}")
                db.add(c); db.flush(); checks.append(c)
                d = _discrepancy(run_id, c.check_id, "amount_mismatch", "high",
                                 f"Cannot find bank payment matching invoice {inv.invoice_number}.",
                                 "Verify payment was made and bank statement is complete.")
                db.add(d); discrepancies.append(d)
        else:
            for ct in ["payment_amount_match", "payment_before_invoice_date", "payment_before_grn_date"]:
                c = _check(run_id, ct, "not_applicable", explanation="Skipped — Invoice or Bank Statement missing")
                db.add(c); checks.append(c)

        # ── 6.6 Risk Score & Overall Status ──────────────────────────────────
        total_risk = sum(SEVERITY_WEIGHTS.get(d.severity, 0) for d in discrepancies)
        risk_score = min(100, total_risk)

        if missing:
            overall_status = "incomplete"
        elif risk_score == 0:
            overall_status = "clean"
        elif risk_score < 20:
            overall_status = "flagged"
        else:
            overall_status = "critical"

        run.overall_risk_score = Decimal(str(risk_score))
        run.overall_status = overall_status
        from datetime import datetime
        run.completed_at = datetime.utcnow()

        # Update bundle status so it is no longer stuck in 'verifying'
        if overall_status == "clean":
            bundle.status = "verified"
        elif overall_status in ("flagged", "critical"):
            bundle.status = "flagged"
        elif overall_status == "incomplete":
            bundle.status = "incomplete"

        db.add(bundle)
        db.add(run)
        db.commit()

        logger.info(
            f"[Verification Service] Bundle {bundle_id} — Status: {overall_status}, "
            f"Risk Score: {risk_score}, Checks: {len(checks)}, Discrepancies: {len(discrepancies)}"
        )
        return run

verification_service = VerificationService()
