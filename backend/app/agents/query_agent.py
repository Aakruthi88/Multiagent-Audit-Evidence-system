"""
QueryAgent - backend/app/agents/query_agent.py
----------------------------------------------
QA Agent for multi-agent evidence system (TASK 5).

Answers user questions strictly using the retrieved evidence_table
and deterministic verification results.
- Authoritative Source of Truth: Deterministic Verification Engine.
- LLM synthesizes natural-language explanations without inventing facts, changing verdicts, or speculating.
- Returns standardized response contract including deduplicated findings and locked source documents.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.agents.llm_rules import GROUNDING_RULES
from app.agents.search_agent import _fetch_bundle_source_documents
from app.agents.state import BundleState
from app.core.config import settings
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import (
    AgentExecutionLog, AuditBundle, BankStatement, BankTransaction,
    Discrepancy, Document, GRN, GRNLineItem, Invoice, InvoiceLineItem,
    PurchaseOrder, POLineItem, Vendor, VerificationCheck, VerificationRun,
)

_query_http_client: Optional[httpx.Client] = None

def _get_query_http_client() -> httpx.Client:
    global _query_http_client
    if _query_http_client is None or _query_http_client.is_closed:
        _query_http_client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    return _query_http_client


def _clean_answer_text(raw_text: str) -> str:
    """Strip thinking process or preambles from response text using tag extraction with fallback."""
    if not raw_text:
        return ""
    text = raw_text.strip()

    tag_match = re.search(r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>", text, re.DOTALL | re.IGNORECASE)
    if tag_match:
        text = tag_match.group(1).strip()
    else:
        # Only apply heuristic stripping when the text is CLEARLY dominated by thinking-process boilerplate.
        thinking_indicators = [
            "thinking process", "analyze user request", "examine evidence table",
            "check grounding rules", "<think>"
        ]
        if any(k in text.lower() for k in thinking_indicators):
            # Remove any <think>...</think> blocks
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
            parts = text.split("\n\n")
            non_thinking = [
                p for p in parts
                if not re.match(r"^\d+\.\s*\*\*", p.strip()) and
                   not any(k in p.lower() for k in thinking_indicators)
            ]
            if non_thinking and len(non_thinking) >= len(parts) // 2:
                text = "\n\n".join(non_thinking).strip()

    text = re.sub(r"^```(?:markdown|text)?\n?", "", text, flags=re.I)
    text = re.sub(r"\n?```$", "", text, flags=re.I)
    return text.strip()


def _sanitize_clean_verification_answer(text: str, is_clean_verif: bool) -> str:
    """Correct any oxymoronic LLM phrasing where a clean item is said to be 'flagged because all checks passed' or hallucinating a reason."""
    if not text or not is_clean_verif:
        return text

    pattern1 = re.compile(
        r"(?i)\b((?:TXN|INV|PO|GRN|Invoice|Transaction|Bundle)?\s*[-A-Z0-9_]*\s*)was flagged because (?:the deterministic verification results? (?:show|indicate) that )?all checks passed",
    )
    text = pattern1.sub(r"\1was NOT flagged. All deterministic verification checks passed", text)

    pattern2 = re.compile(
        r"(?i)\b((?:TXN|INV|PO|GRN|Invoice|Transaction|Bundle)?\s*[-A-Z0-9_]*\s*)was flagged due to (?:a |the )?(?:user's )?(?:misunderstanding|assumption|premise)",
    )
    text = pattern2.sub(r"\1was NOT flagged. Any assumption of failure is incorrect as all checks passed", text)

    pattern3 = re.compile(
        r"(?i)\b((?:TXN|INV|PO|GRN|Invoice|Transaction|Bundle)?\s*[-A-Z0-9_]*\s*)was flagged because (?:it was|the transaction was|the invoice was) verified clean",
    )
    text = pattern3.sub(r"\1was NOT flagged; it was verified clean", text)

    pattern4 = re.compile(
        r"(?i)\b((?:TXN|INV|PO|GRN|Invoice|Transaction|Bundle)?\s*[-A-Z0-9_]*\s*)was flagged because\b.*?(?=\.|$)",
    )
    text = pattern4.sub(r"\1was NOT flagged. All 3-way and 4-way matching checks passed clean with zero discrepancies (Risk Score: 0/100).", text)

    return text


def _filter_evidence_for_prompt(user_query: str, evidence: dict, plan: Optional[dict] = None) -> dict:
    """Filter evidence_table to present clean, relevant document data to the LLM."""
    req_docs = plan.get("required_documents") if plan else None
    if isinstance(req_docs, list) and len(req_docs) > 0:
        req_set = {str(d).lower().strip() for d in req_docs}
    else:
        req_set = {"invoice", "purchase_order", "grn", "bank_statement"}

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name")
    customer = evidence.get("customer_name") or inv.get("customer_name") or po.get("customer_name") or inv.get("bill_to")

    filtered = {}
    if vendor:
        filtered["vendor_name"] = vendor
    if customer:
        filtered["customer_name"] = customer

    if "invoice" in req_set and inv:
        doc_inv = {"invoice_number": inv.get("invoice_number")}
        for f in ("subtotal", "tax_amount", "total_amount", "invoice_date", "due_date", "purchase_order", "po_number", "vendor_name", "customer_name", "bill_to"):
            if inv.get(f) is not None:
                doc_inv[f] = inv.get(f)
        if inv.get("line_items"):
            doc_inv["line_items"] = inv.get("line_items")
        filtered["invoice"] = doc_inv

    if "purchase_order" in req_set and po:
        doc_po = {"po_number": po.get("po_number")}
        for f in ("subtotal", "tax_amount", "total_amount", "po_date", "vendor_name", "customer_name", "buyer_name"):
            if po.get(f) is not None:
                doc_po[f] = po.get(f)
        if po.get("line_items"):
            doc_po["line_items"] = po.get("line_items")
        filtered["purchase_order"] = doc_po

    if "grn" in req_set and grn:
        doc_grn = {"grn_number": grn.get("grn_number")}
        for f in ("grn_date", "delivery_note_number", "received_condition", "total_amount", "vendor_name"):
            if grn.get(f) is not None:
                doc_grn[f] = grn.get(f)
        if grn.get("line_items"):
            doc_grn["line_items"] = grn.get("line_items")
        filtered["grn"] = doc_grn

    if "bank_statement" in req_set and bank:
        doc_bank = {}
        if bank.get("account_number"):
            doc_bank["account_number"] = bank.get("account_number")
        if bank.get("payment_status"):
            doc_bank["payment_status"] = bank.get("payment_status")
        if bank.get("transactions"):
            doc_bank["transactions"] = bank.get("transactions")[:5]
        filtered["bank_statement"] = doc_bank

    return filtered if filtered else evidence


def _format_amount(val) -> str:
    if val is None or val == "":
        return "N/A"
    try:
        f = float(str(val).replace("₹", "").replace(",", "").replace("Rs.", "").strip())
        if f.is_integer():
            return f"₹{int(f):,}"
        return f"₹{f:,.2f}"
    except Exception:
        return f"₹{val}"


_CHECK_TITLES = {
    "po_invoice_total_match": "PO ↔ Invoice Amount Match",
    "po_invoice_ref_match": "PO ↔ Invoice Reference Match",
    "po_invoice_vendor_match": "Vendor Match (PO ↔ Invoice)",
    "po_grn_amount_match": "PO ↔ GRN Amount Match (Pre-Tax)",
    "grn_qty_match": "PO ↔ GRN Quantity Match",
    "grn_qty_short_shipment": "Short Shipment (GRN Qty < PO Qty)",
    "grn_qty_over_delivery": "Over Delivery (GRN Qty > PO Qty)",
    "grn_qty_zero_received": "Zero Quantity Received",
    "invoice_grn_amount_match": "Invoice ↔ GRN Amount Match",
    "tax_rate_consistency": "Tax Rate Consistency",
    "invoice_arithmetic_check": "Invoice Internal Arithmetic",
    "payment_amount_match": "Invoice ↔ Bank Debit Amount Match",
    "payment_before_invoice_date": "Payment Date Chronology (Invoice)",
    "payment_before_grn_date": "Payment Date Chronology (GRN)",
    "payment_matched_to_invoice": "Bank Payment Narration Match",
    "doc_completeness_purchase_order": "Document Completeness (PO)",
    "doc_completeness_invoice": "Document Completeness (Invoice)",
    "doc_completeness_grn": "Document Completeness (GRN)",
    "doc_completeness_bank_statement": "Document Completeness (Bank Statement)",
}


def _format_check_block(c: dict, evidence: dict) -> str:
    status = (c.get("status") or "").lower()
    check_type = c.get("check_type") or c.get("check_name") or "Check"
    title = _CHECK_TITLES.get(check_type, check_type.replace("_", " ").title())

    if status == "pass":
        symbol = "✓"
        res_str = "PASS"
    elif status == "fail":
        symbol = "✕"
        res_str = "FAIL"
    elif status == "warning":
        symbol = "⚠"
        res_str = "WARNING"
    else:
        symbol = "ℹ"
        res_str = status.upper()

    lines = [f"{symbol} {title}"]

    expected = c.get("expected")
    actual = c.get("actual")
    variance = c.get("variance")

    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}

    if check_type == "po_invoice_total_match":
        inv_tot = _format_amount(inv.get("total_amount") or actual)
        po_tot = _format_amount(po.get("total_amount") or expected)
        lines.append(f"PO Gross Total: {po_tot}")
        lines.append(f"Invoice Gross Total: {inv_tot}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "po_invoice_ref_match":
        lines.append(f"PO Number: {po.get('po_number') or expected or 'N/A'}")
        lines.append(f"Invoice Stated PO Ref: {inv.get('po_number') or inv.get('purchase_order') or actual or 'N/A'}")
    elif check_type == "po_invoice_vendor_match":
        po_vendor = po.get("vendor_name") or evidence.get("vendor_name") or expected or "N/A"
        inv_vendor = inv.get("vendor_name") or evidence.get("vendor_name") or actual or "N/A"
        lines.append(f"PO Vendor: {po_vendor}")
        lines.append(f"Invoice Vendor: {inv_vendor}")
    elif check_type in ("grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received"):
        po_qty = expected if expected is not None else "N/A"
        grn_qty = actual if actual is not None else "N/A"
        lines.append(f"PO Ordered Qty: {po_qty} units")
        lines.append(f"GRN Received Qty: {grn_qty} units")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {variance} units")
    elif check_type == "po_grn_amount_match":
        po_sub = _format_amount(po.get("subtotal") or expected)
        grn_tot = _format_amount(grn.get("total_amount") or actual)
        lines.append(f"PO Pre-Tax Subtotal: {po_sub}")
        lines.append(f"GRN Pre-Tax Total: {grn_tot} (evaluated on pre-tax basis)")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "invoice_grn_amount_match":
        inv_sub = _format_amount(inv.get("subtotal") or expected)
        grn_tot = _format_amount(grn.get("total_amount") or actual)
        lines.append(f"Invoice Pre-Tax Subtotal: {inv_sub}")
        lines.append(f"GRN Pre-Tax Total: {grn_tot} (evaluated on pre-tax basis)")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {_format_amount(variance)}")
    elif check_type == "tax_rate_consistency":
        lines.append(f"PO Tax Rate: {expected}%")
        lines.append(f"Invoice Tax Rate: {actual}%")
    elif check_type == "invoice_arithmetic_check":
        lines.append(f"Calculated Subtotal + Tax: {_format_amount(expected)}")
        lines.append(f"Invoice Stated Gross Total: {_format_amount(actual)}")
    elif expected is not None or actual is not None:
        if expected is not None:
            lines.append(f"Expected: {expected}")
        if actual is not None:
            lines.append(f"Actual: {actual}")
        if variance and str(variance) not in ("0", "0.0", "0.00", "None"):
            lines.append(f"Difference: {variance}")

    if c.get("explanation"):
        lines.append(f"Detail: {c.get('explanation')}")

    lines.append(f"Result: {res_str}")
    return "\n".join(lines)


def _get_quantity_summary(evidence: dict) -> str:
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    po_lines = po.get("line_items") or []
    grn_lines = grn.get("line_items") or []

    po_qty = sum(float(l.get("qty", 0) or 0) for l in po_lines) if po_lines else None
    grn_qty = sum(float(l.get("qty_received", 0) or 0) for l in grn_lines) if grn_lines else None

    if po_qty is not None and grn_qty is not None:
        po_str = f"{int(po_qty) if po_qty.is_integer() else po_qty} units"
        grn_str = f"{int(grn_qty) if grn_qty.is_integer() else grn_qty} units"
        if po_qty == grn_qty:
            return f"{po_str} (Matched)"
        diff = abs(po_qty - grn_qty)
        diff_str = f"{int(diff) if diff.is_integer() else diff} units"
        return f"PO: {po_str} | GRN: {grn_str} (Difference: {diff_str})"
    elif po_qty is not None:
        return f"{int(po_qty) if po_qty.is_integer() else po_qty} units"
    elif grn_qty is not None:
        return f"{int(grn_qty) if grn_qty.is_integer() else grn_qty} units"
    return "N/A"


def _determine_overall_status(verdict: Optional[str], checks: List[dict], risk_score: float) -> str:
    v = (verdict or "").lower()
    if v == "clean" or (not any(c.get("status") in ("fail", "warning") for c in checks) and risk_score == 0):
        return "VERIFIED"
    if v == "critical" or any(c.get("status") == "fail" for c in checks) or risk_score >= 20:
        return "FAILED"
    if any(c.get("status") == "warning" for c in checks) or risk_score > 0:
        return "REVIEW REQUIRED"
    return "VERIFIED"


def _filter_checks_for_query(checks: List[dict], user_query: str) -> List[dict]:
    """
    Return checks prioritized for the specific user question.
    """
    q = (user_query or "").lower()
    if not checks:
        return []

    # Amount questions
    if any(k in q for k in ["amount", "total", "subtotal", "tax", "arithmetic", "price", "mismatch"]):
        amount_types = {
            "po_invoice_total_match", "po_grn_amount_match", "invoice_grn_amount_match",
            "invoice_arithmetic_check", "tax_rate_consistency", "payment_amount_match"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in amount_types]
        if prioritized:
            return prioritized

    # GRN / quantity questions
    if any(k in q for k in ["grn", "quantity", "qty", "deliver", "received", "goods receipt", "short shipment", "over delivery"]):
        grn_types = {
            "grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received",
            "po_grn_amount_match", "invoice_grn_amount_match", "doc_completeness_grn"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in grn_types]
        if prioritized:
            return prioritized

    # Payment / Bank statement questions
    if any(k in q for k in ["paid", "payment", "bank", "debit", "transaction"]):
        pay_types = {
            "payment_amount_match", "payment_before_invoice_date", "payment_before_grn_date",
            "payment_matched_to_invoice", "doc_completeness_bank_statement"
        }
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in pay_types]
        if prioritized:
            return prioritized

    # Vendor questions
    if any(k in q for k in ["vendor", "supplier", "seller"]):
        vendor_types = {"po_invoice_vendor_match"}
        prioritized = [c for c in checks if (c.get("check_type") or c.get("check_name")) in vendor_types]
        if prioritized:
            return prioritized

    return [c for c in checks if (c.get("status") or "").lower() != "not_applicable"]


def _format_deterministic_verification_response(evidence: dict, verification_info: dict, bundle_id: Optional[str] = None, user_query: str = "") -> str:
    """Generate comprehensive structured Markdown verification response grounded purely in deterministic results."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "N/A"

    checks = verification_info.get("checks") or []
    discrepancies = verification_info.get("discrepancies") or []
    verdict = verification_info.get("verdict")
    risk_score = float(verification_info.get("risk_score") or 0.0)

    overall_status = verification_info.get("overall_status") or _determine_overall_status(verdict, checks, risk_score)

    passed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "pass")
    failed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "fail")
    warning_count = sum(1 for c in checks if (c.get("status") or "").lower() == "warning")
    disc_count = len(discrepancies) if discrepancies else (failed_count + warning_count)

    po_num = po.get("po_number") or inv.get("po_number") or inv.get("purchase_order") or "N/A"
    inv_num = inv.get("invoice_number") or "N/A"
    grn_num = grn.get("grn_number") or "N/A"

    inv_total_str = _format_amount(inv.get("total_amount"))
    inv_subtotal_str = _format_amount(inv.get("subtotal"))
    inv_tax_str = _format_amount(inv.get("tax_amount"))
    po_total_str = _format_amount(po.get("total_amount") or po.get("subtotal"))
    po_subtotal_str = _format_amount(po.get("subtotal"))
    po_tax_str = _format_amount(po.get("tax_amount"))
    grn_total_str = _format_amount(grn.get("total_amount"))
    qty_str = _get_quantity_summary(evidence)

    # Transaction / Bank context if available (critical for investigation queries)
    txn_details = []
    if bank.get("transactions"):
        for t in bank.get("transactions")[:3]:
            t_ref = t.get("transaction_reference") or t.get("reference")
            t_amt = _format_amount(t.get("amount") or t.get("debit_amount") or t.get("debit"))
            t_st = t.get("status") or bank.get("payment_status") or "recorded"
            t_date = t.get("date") or t.get("transaction_date")
            desc = t.get("description") or t.get("narration")
            ref_str = f" Ref: {t_ref}," if t_ref else ""
            date_str = f" Date: {t_date}," if t_date else ""
            desc_str = f" Narration: '{desc}'," if desc else ""
            txn_details.append(f"- Transaction:{ref_str}{date_str} Debit: {t_amt}, Status: {t_st},{desc_str}".rstrip(","))
    elif bank.get("payment_status") or bank.get("account_number"):
        acc = bank.get("account_number", "N/A")
        pst = bank.get("payment_status", "N/A")
        txn_details.append(f"- Bank Account: {acc}, Payment Status: {pst}")

    txn_section = ""
    if txn_details:
        txn_section = "\n### Linked Transaction & Payment Evidence:\n" + "\n".join(txn_details) + "\n"

    # Determine check verbosity dynamically based on user query
    q_lower = (user_query or "").lower()
    wants_all_checks = any(k in q_lower for k in ["all check", "every check", "detailed check", "full check", "full report", "detailed report", "audit report"])

    failed_or_warn = [c for c in checks if (c.get("status") or "").lower() in ("fail", "warning")]
    prioritized_checks = _filter_checks_for_query(checks, user_query)

    blocks_to_render = []
    rendered_check_types = set()

    if wants_all_checks:
        for c in checks:
            if (c.get("status") or "").lower() != "not_applicable":
                blocks_to_render.append(_format_check_block(c, evidence))
        checks_str = "\n\n".join(blocks_to_render) if blocks_to_render else "No relevant verification checks recorded."
    else:
        # 1. Always format all failed/warning checks in full
        for c in failed_or_warn:
            ct = c.get("check_type") or c.get("check_name")
            rendered_check_types.add(ct)
            blocks_to_render.append(_format_check_block(c, evidence))

        # 2. Format query-prioritized checks in full
        for c in prioritized_checks:
            ct = c.get("check_type") or c.get("check_name")
            if ct not in rendered_check_types and (c.get("status") or "").lower() != "not_applicable":
                rendered_check_types.add(ct)
                blocks_to_render.append(_format_check_block(c, evidence))

        # 3. If everything passed and no specific checks prioritized, format top core checks
        if not blocks_to_render:
            core_types = ["po_invoice_total_match", "po_invoice_ref_match", "po_invoice_vendor_match"]
            for c in checks:
                ct = c.get("check_type") or c.get("check_name")
                if ct in core_types and (c.get("status") or "").lower() != "not_applicable":
                    rendered_check_types.add(ct)
                    blocks_to_render.append(_format_check_block(c, evidence))

        # 4. Compactly list any other passing checks without redundant multi-line bloat
        other_passed = [
            c for c in checks
            if (c.get("status") or "").lower() == "pass" and (c.get("check_type") or c.get("check_name")) not in rendered_check_types
        ]
        if other_passed:
            passed_names = [_CHECK_TITLES.get(c.get("check_type") or c.get("check_name"), (c.get("check_type") or c.get("check_name") or "Check").replace("_", " ").title()) for c in other_passed]
            compact_passed_str = f"✓ Additional Passed Checks ({len(other_passed)}): " + ", ".join(passed_names)
            blocks_to_render.append(compact_passed_str)

        checks_str = "\n\n".join(blocks_to_render) if blocks_to_render else "No relevant verification checks recorded."

    # Findings / Exceptions with deduplication
    findings = []
    seen_exps = set()
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in ("fail", "warning"):
            exp = c.get("explanation") or f"Check {c.get('check_name')} resulted in {st}."
            if exp not in seen_exps:
                seen_exps.add(exp)
                sev = (c.get("severity") or "").upper()
                sev_str = f" [{sev}]" if sev else ""
                findings.append(f"- {exp}{sev_str}")

    for d in discrepancies:
        desc = d.get("description")
        if desc and desc not in seen_exps and not any(desc in f for f in findings):
            seen_exps.add(desc)
            rec = d.get("recommended_action")
            rec_str = f" Action: {rec}" if rec else ""
            findings.append(f"- {desc}{rec_str}")

    findings_str = "\n".join(findings) if findings else "No discrepancies or exceptions found. All deterministic checks passed."

    return f"""## Deterministic Verification Findings (SOURCE OF TRUTH)
Overall Status: {overall_status}
Verdict: {verdict or overall_status}
Risk Score: {int(risk_score)}/100
Invoice: {inv_num} (Total: {inv_total_str} [Pre-Tax Subtotal: {inv_subtotal_str}, Tax: {inv_tax_str}])
Purchase Order: {po_num} (Total: {po_total_str} [Pre-Tax Subtotal: {po_subtotal_str}, Tax: {po_tax_str}])
GRN: {grn_num} (Total: {grn_total_str} [Pre-Tax Received Amount matching PO/Invoice Subtotal])
Vendor: {vendor}
Quantity: {qty_str}
Checks Passed: {passed_count}, Checks Failed: {failed_count}, Warnings: {warning_count}{txn_section}
### Relevant Checks:
{checks_str}

### Discrepancies & Findings:
{findings_str}"""


_VERIFICATION_SYSTEM_PROMPT = GROUNDING_RULES + """
You are an enterprise Audit Intelligence Assistant.
The deterministic verification engine has executed all 3-way and 4-way matching rules against the source documents and is the AUTHORITATIVE SOLE SOURCE OF TRUTH.

Your task is to write a clear, complete, professional natural-language audit explanation that directly answers the user's specific question (e.g. whether documents match, why a transaction or bundle was flagged/failed, total amounts, or payment status).

CRITICAL GROUNDING & ACCURACY RULES:
1. Direct Answer: Answer the user's question directly in the opening sentence. State what was verified, exact document numbers (Invoice #, PO #, GRN #), exact amounts or quantities in ₹, and the verdict or findings clearly.
2. Absolute Grounding: Answer ONLY from the supplied deterministic verification results and evidence table. Do NOT invent, assume, alter, or infer numbers, dates, or causes.
3. Sole Source of Truth: The deterministic verification engine is the sole authority for amounts, match statuses, check results, risk scores, discrepancies, and verdicts. Keep your role strictly to explaining these results in plain English.
4. Financial Reconciliation & Tax Basis: When comparing GRN against PO or Invoice, note that GRN amounts represent pre-tax received values which match pre-tax subtotals, while Invoice/PO gross totals include tax. Do not treat tax differences between GRN subtotal and Invoice gross total as a discrepancy when the pre-tax amounts match and the check passed.
5. Conflicting User Assumptions & Clean Status: If the user's question asks why an entity (transaction, invoice, PO, or bundle) was 'flagged', 'failed', 'rejected', or had discrepancies, but the deterministic verification status is VERIFIED / clean with 0 risk score and 0 discrepancies:
   - You MUST explicitly state in the opening sentence that the item was NOT flagged or failed.
   - NEVER write that an item "was flagged because all checks passed" or "was flagged due to passing checks". That is a contradiction.
   - State clearly: The transaction/invoice was NOT flagged. It passed all deterministic verification checks with a risk score of 0/100 and zero discrepancies.
   - Then provide the supporting clean verification numbers (PO, Invoice, GRN totals in ₹, matched quantities, and passed checks).
6. Failure / Flagging Reasons: If a bundle or transaction genuinely failed or was flagged with discrepancies, explain the actual retrieved deterministic evidence (e.g. overbilling variance, goods unconfirmed, bank debit mismatch). If no failure reason or discrepancy exists in the retrieved evidence, you must state that clearly.
7. Zero Speculation: Do NOT use speculation words ("fraud", "unauthorized", "backdated", "approved") unless explicitly stated in the deterministic findings. If evidence is missing or ambiguous, state clearly that it cannot be determined from the available documents.
8. No Redundant Headers: Do NOT output markdown section headers (like "## Verification Result" or "### Summary"). The UI renders structured tables and badges automatically below your response.
9. Completeness: Include all essential financial details (totals in ₹, subtotal and tax breakdowns, dates, check counts, and specific discrepancies) without artificial brevity or filler text."""


def _normalize_vendor_str(v: Optional[str]) -> str:
    """Normalize vendor name for robust matching by stripping corporate suffixes and non-alphanumeric chars."""
    if not v:
        return ""
    s = str(v).lower()
    s = re.sub(r'\b(?:pvt|ltd|private|limited|inc|corp|corporation|llc|co|company|enterprises|technologies|solutions|group|holdings)\b', '', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s.strip()


def _are_vendors_matching(v_req: Optional[str], v_act: Optional[str]) -> bool:
    """Check if requested vendor name matches the actual vendor in retrieved evidence."""
    if not v_req or not v_act:
        return True
    norm_req = _normalize_vendor_str(v_req)
    norm_act = _normalize_vendor_str(v_act)
    if not norm_req or not norm_act:
        return True
    if norm_req in norm_act or norm_act in norm_req:
        return True
    # Token overlap check
    stop_tokens = {"pvt", "ltd", "private", "limited", "inc", "corp", "company", "and", "the", "for", "with", "from"}
    words_req = set(re.findall(r'[a-z0-9]{3,}', str(v_req).lower())) - stop_tokens
    words_act = set(re.findall(r'[a-z0-9]{3,}', str(v_act).lower())) - stop_tokens
    if words_req and words_act and bool(words_req & words_act):
        return True
    return False


def _extract_requested_vendor(user_query: str) -> Optional[str]:
    """
    Extract explicitly requested vendor name from the user query.
    Handles patterns like:
      - from <Vendor>
      - by <Vendor>
      - vendor: <Vendor> / vendor <Vendor>
      - supplier <Vendor>
      - corporate names ending in Ltd, Pvt Ltd, Inc, Corp, LLC, Technologies, etc.
    """
    if not user_query:
        return None
    q = user_query.strip()

    stop_words = {
        "invoice", "po", "purchase order", "grn", "bank", "statement", "the", "a", "an",
        "our", "my", "this", "that", "these", "those", "records", "evidence", "system",
        "database", "documents", "files", "all", "each", "any", "which", "what", "where",
        "when", "how", "details", "data", "laptop", "laptops", "purchase", "order", "delivery", "us"
    }

    # 1. Look for explicit "from/by/vendor/supplier/seller <Name>"
    patterns = [
        r'(?i)\b(?:from|by|vendor\s*[:\-]?|supplier\s*[:\-]?|seller\s*[:\-]?|purchased?\s+from|bought\s+from|issued\s+by)\s+([A-Za-z0-9&.,\'\-\s]+?)(?:\s+(?:for\s+|dated\s+|with\s+|on\s+|in\s+|against\s+|where\s+|bundle\s+|txn\s+|po\s+|inv\s+|invoice\s+|purchase\s+|to\b)|\?|\.|$|\n)',
    ]

    for pat in patterns:
        m = re.search(pat, q)
        if m:
            cand = m.group(1).strip().strip(",.-")
            # Remove trailing clause markers
            cand = re.sub(r'(?i)\s+(?:for\s+|dated\s+|with\s+|on\s+|in\s+|where\s+|bundle\s+|txn\s+|po\s+|inv\s+|invoice\s+|purchase\s+).*$', '', cand).strip()
            if cand and cand.lower() not in stop_words and len(cand) >= 2:
                if not re.match(r'^(?:INV|PO|GRN|TXN|DN)?[-_\s]?\d+$', cand, re.I) and not re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}$', cand):
                    return cand

    # 2. Look for standalone corporate entity names: "ABC Ltd", "XYZ Pvt Ltd", "Acme Corp", "Dell Technologies"
    corp_match = re.search(
        r'\b([A-Z0-9][A-Za-z0-9&.,\'\-\s]{1,40}\b(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Ltd\.?|Inc\.?|LLC|Corp\.?|Corporation|Technologies|Enterprises|Solutions))\b',
        q
    )
    if corp_match:
        cand = corp_match.group(1).strip().strip(",.-")
        if cand and cand.lower() not in stop_words:
            return cand

    return None


def validate_query_entity_grounding(user_query: str, evidence: dict) -> Dict[str, Any]:
    """
    Intelligent entity-grounding validation before LLM synthesis.
    Validates requested entity and document references against retrieved structured evidence,
    accurately distinguishing between seller/vendor and buyer/customer roles.
    """
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    act_vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name")
    act_customer = evidence.get("customer_name") or inv.get("customer_name") or po.get("customer_name") or inv.get("bill_to")
    act_inv_num = inv.get("invoice_number")
    act_po_num = po.get("po_number")

    req_entity = _extract_requested_vendor(user_query)

    # Check invoice number in query
    req_inv_matches = re.findall(r'\b(?:INV|invoice|tax\s+invoice)\b[#\s_:-]*([a-zA-Z0-9\-_]{3,20})\b', user_query, re.I)
    req_inv = req_inv_matches[0] if req_inv_matches else None
    if not req_inv:
        digit_m = re.findall(r'\b\d{5,6}\b', user_query)
        if digit_m and any(k in user_query.lower() for k in ["invoice", "inv"]):
            req_inv = digit_m[0]

    # Check PO number in query
    req_po_matches = re.findall(r'\b(?:PO|purchase\s+order)\b[#\s_:-]*([a-zA-Z0-9\-_]{3,20})\b', user_query, re.I)
    req_po = req_po_matches[0] if req_po_matches else None

    is_vendor_match = False
    is_customer_match = False
    vendor_mismatch = False

    if req_entity:
        if act_vendor and _are_vendors_matching(req_entity, act_vendor):
            is_vendor_match = True
        elif act_customer and _are_vendors_matching(req_entity, act_customer):
            is_customer_match = True
        elif act_vendor:
            vendor_mismatch = True

    def _norm_code(c):
        return re.sub(r'[^a-zA-Z0-9]', '', str(c or '')).lower()

    inv_mismatch = False
    if req_inv and act_inv_num:
        if _norm_code(req_inv) != _norm_code(act_inv_num):
            inv_mismatch = True

    po_mismatch = False
    if req_po and act_po_num:
        if _norm_code(req_po) != _norm_code(act_po_num):
            po_mismatch = True

    has_mismatch = vendor_mismatch or inv_mismatch or po_mismatch

    matching_aspects = []
    mismatch_aspects = []

    # Find line items
    all_line_descs = []
    for doc in (inv, po, grn):
        for item in (doc.get("line_items") or []):
            desc = item.get("description") or item.get("item_name")
            if desc and desc not in all_line_descs:
                all_line_descs.append(desc)

    if all_line_descs:
        matching_aspects.append(f"Purchased item(s): {', '.join(all_line_descs[:3])}")
    if act_inv_num and not inv_mismatch:
        matching_aspects.append(f"Invoice Number: {act_inv_num}")
    if inv.get("total_amount"):
        matching_aspects.append(f"Invoice Total: {_format_amount(inv.get('total_amount'))}")
    if act_vendor:
        matching_aspects.append(f"Seller / Vendor: {act_vendor}")
    if act_customer:
        matching_aspects.append(f"Customer (Bill To): {act_customer}")

    if vendor_mismatch:
        mismatch_aspects.append(
            f"Vendor Mismatch: You requested records for entity '{req_entity}', but the retrieved records (Invoice {act_inv_num or 'N/A'}) are issued by vendor '{act_vendor}'. No records exist for '{req_entity}'."
        )
    if inv_mismatch:
        mismatch_aspects.append(
            f"Invoice Number Mismatch: Requested Invoice '{req_inv}', but retrieved Invoice is '{act_inv_num}'."
        )
    if po_mismatch:
        mismatch_aspects.append(
            f"PO Number Mismatch: Requested PO '{req_po}', but retrieved PO is '{act_po_num}'."
        )

    explanation_lines = []
    if vendor_mismatch:
        inv_str = f"Invoice {act_inv_num}" if act_inv_num else "The retrieved record"
        items_str = f" for {all_line_descs[0]}" if all_line_descs else ""
        explanation_lines.append(
            f"Entity Mismatch Detected: {inv_str}{items_str} was issued by vendor '{act_vendor}', not '{req_entity}'."
        )
        explanation_lines.append(
            f"The retrieved evidence shows that '{act_vendor}' is the actual vendor on record. No evidence or invoices were found for '{req_entity}'."
        )
        if inv.get("total_amount"):
            inv_total = _format_amount(inv.get("total_amount"))
            sub_str = f" (Subtotal: {_format_amount(inv.get('subtotal'))}, Tax: {_format_amount(inv.get('tax_amount'))})" if inv.get("subtotal") else ""
            date_str = f", dated {inv.get('invoice_date')}" if inv.get('invoice_date') else ""
            explanation_lines.append(
                f"For the matched transaction ({inv_str}), the total amount is {inv_total}{sub_str}{date_str}."
            )
    elif is_customer_match:
        inv_str = f"Invoice {act_inv_num}" if act_inv_num else "The retrieved invoice"
        items_str = f" for {all_line_descs[0]}" if all_line_descs else ""
        inv_total = _format_amount(inv.get("total_amount")) if inv.get("total_amount") else ""
        explanation_lines.append(
            f"{inv_str}{items_str} was issued by vendor '{act_vendor}' to customer '{act_customer}' (Bill To) for a total of {inv_total}."
        )
    elif inv_mismatch:
        explanation_lines.append(
            f"Invoice Mismatch: Requested invoice '{req_inv}' was not found. The retrieved evidence corresponds to Invoice '{act_inv_num}' from vendor '{act_vendor}'."
        )

    return {
        "has_mismatch": has_mismatch,
        "vendor_mismatch": vendor_mismatch,
        "is_customer_match": is_customer_match,
        "is_vendor_match": is_vendor_match,
        "invoice_mismatch": inv_mismatch,
        "po_mismatch": po_mismatch,
        "requested_vendor": req_entity if vendor_mismatch else None,
        "requested_entity": req_entity,
        "actual_vendor": act_vendor,
        "actual_customer": act_customer,
        "requested_invoice": req_inv,
        "actual_invoice": act_inv_num,
        "requested_po": req_po,
        "actual_po": act_po_num,
        "matching_aspects": matching_aspects,
        "mismatch_aspects": mismatch_aspects,
        "deterministic_explanation": " ".join(explanation_lines) if explanation_lines else ""
    }


def _sanitize_entity_mismatch_answer(text: str, validation_result: Optional[Dict[str, Any]]) -> str:
    """Ensure LLM response never claims a requested mismatch vendor issued the invoice or conflates vendors."""
    if not text or not validation_result or not validation_result.get("has_mismatch"):
        return text
    if validation_result.get("is_customer_match"):
        return text

    req_v = validation_result.get("requested_vendor")
    act_v = validation_result.get("actual_vendor")
    det_exp = validation_result.get("deterministic_explanation") or ""

    if validation_result.get("vendor_mismatch") and req_v and act_v:
        # 1. Replace any blended "(requested_vendor) (vendor name: ...)"
        blended_pattern = re.compile(
            rf"(?i)\b{re.escape(req_v)}\s*\(\s*(?:vendor\s+name\s*:\s*)?[^)]+\)",
            re.IGNORECASE
        )
        text = blended_pattern.sub(f"{act_v} (requested entity '{req_v}' does not match vendor)", text)

        # 2. Replace "{req_v} issued/provided/billed/sold" -> "{act_v} issued"
        issued_pattern = re.compile(
            rf"(?i)\b{re.escape(req_v)}\s+(?:issued|provided|billed|created|submitted|sold)\b",
            re.IGNORECASE
        )
        text = issued_pattern.sub(f"{act_v} issued", text)

        # 3. If the answer does not acknowledge the mismatch or still has misleading attribution
        if req_v.lower() in text.lower() and not any(k in text.lower() for k in ["mismatch", f"not {req_v.lower()}", f"no records for {req_v.lower()}", "does not match"]):
            return det_exp

    return text


def _build_template_answer(user_query: str, evidence: dict, plan: Optional[dict] = None, validation_result: Optional[dict] = None) -> str:
    """Deterministic fallback QA answer grounded strictly in retrieved evidence when LLM is unavailable."""
    if validation_result and validation_result.get("has_mismatch") and validation_result.get("deterministic_explanation"):
        return validation_result["deterministic_explanation"]

    q_lower = (user_query or "").lower()
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "Vendor"
    customer = evidence.get("customer_name") or inv.get("customer_name") or po.get("customer_name") or inv.get("bill_to")

    # If asking for evidence / laptop purchase / customer purchase
    if any(k in q_lower for k in ["evidence", "purchase", "laptop", "buy", "order", "invoice"]) and inv:
        num = inv.get("invoice_number", "N/A")
        tot = _format_amount(inv.get("total_amount"))
        sub = _format_amount(inv.get("subtotal"))
        tax = _format_amount(inv.get("tax_amount"))
        lines = inv.get("line_items") or []
        items_str = f" for {lines[0].get('description')}" if lines else ""
        cust_str = f" to customer {customer} (Bill To)" if customer else ""
        return f"Invoice {num}{items_str} was issued by vendor {vendor}{cust_str} for a total of {tot} (Subtotal: {sub}, Tax: {tax})."

    if any(k in q_lower for k in ["total", "amount", "subtotal", "tax", "price"]) and inv:
        tot = inv.get("total_amount")
        num = inv.get("invoice_number", "N/A")
        sub = inv.get("subtotal")
        tax = inv.get("tax_amount")
        if tot is not None:
            breakdown = f" (Subtotal: {_format_amount(sub)}, Tax: {_format_amount(tax)})" if sub is not None and tax is not None else ""
            cust_str = f" to customer {customer}" if customer else ""
            return f"The total of Invoice {num} is {_format_amount(tot)}{breakdown} from vendor {vendor}{cust_str}."
    if any(k in q_lower for k in ["quantity", "qty", "received", "grn", "units"]) and grn:
        lines = grn.get("line_items") or []
        if lines:
            line_str = ", ".join([f"{l.get('description', 'Item')}: received {l.get('qty_received', 0)}" for l in lines])
            return f"GRN {grn.get('grn_number', 'N/A')} received items: {line_str}."
    if any(k in q_lower for k in ["item", "items", "ordered", "po", "purchase order"]) and po:
        lines = po.get("line_items") or []
        if lines:
            line_str = ", ".join([f"{l.get('description', 'Item')} (Qty: {l.get('qty', 0)})" for l in lines])
            return f"PO {po.get('po_number', 'N/A')} ordered items: {line_str}."
    if any(k in q_lower for k in ["paid", "payment", "bank"]) and bank:
        status = bank.get("payment_status", "recorded")
        txns = bank.get("transactions") or []
        if txns:
            t0 = txns[0]
            amt = _format_amount(t0.get("amount") or t0.get("debit_amount") or t0.get("debit"))
            return f"Bank statement confirms payment of {amt} with status: {status}."
        return f"Payment status: {status}."
    return "The requested information is not available in the retrieved evidence."


def _build_result_metadata(evidence: dict, bundle_id: Optional[str], validation_result: Optional[dict] = None) -> dict:
    """Build structured result metadata for frontend display cards."""
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name")
    customer = evidence.get("customer_name") or inv.get("customer_name") or po.get("customer_name") or inv.get("bill_to")

    found = bool(inv or po or grn or bank)
    if not found:
        status = "NOT FOUND"
        verdict = "NOT FOUND"
    elif validation_result and validation_result.get("has_mismatch"):
        status = "MISMATCH"
        verdict = "MISMATCH"
    else:
        status = "VERIFIED"
        verdict = "VERIFIED"

    meta = {
        "found": found,
        "status": status,
        "verdict": verdict,
        "ambiguous": False,
        "bundle_id": bundle_id,
        "vendor_name": vendor,
        "customer_name": customer,
        "invoice_number": inv.get("invoice_number"),
        "po_number": po.get("po_number"),
        "grn_number": grn.get("grn_number"),
        "total_amount": inv.get("total_amount") or po.get("total_amount"),
    }
    if validation_result and validation_result.get("has_mismatch"):
        meta["has_mismatch"] = True
        meta["vendor_mismatch"] = validation_result.get("vendor_mismatch", False)
        meta["invoice_mismatch"] = validation_result.get("invoice_mismatch", False)
        meta["po_mismatch"] = validation_result.get("po_mismatch", False)
        meta["requested_vendor"] = validation_result.get("requested_vendor")
        meta["actual_vendor"] = validation_result.get("actual_vendor")
        meta["actual_customer"] = validation_result.get("actual_customer")
        meta["matching_aspects"] = validation_result.get("matching_aspects", [])
        meta["mismatch_aspects"] = validation_result.get("mismatch_aspects", [])

    return meta


def _build_intent_system_prompt(intent: str = "") -> str:
    return GROUNDING_RULES + """
You are an enterprise Audit Intelligence Assistant.
Answer the user's exact question directly, completely, and professionally using only the supplied evidence.
The supplied evidence contains the verified, matching records retrieved for the query.
Do not invent facts, numbers, dates, or speculative causes.
State specific document numbers, values in ₹ (including subtotal and tax breakdowns where available), dates, and vendor names directly.
Do not claim that a document is missing or not mentioned when its details are present in the evidence table.
If the evidence does not establish an answer to the query, state clearly that the requested information is not available in the retrieved records.
Do not output markdown section headers or raw data dumps.
Return only the final answer text."""


def _is_verification_query(user_query: str, plan: Optional[dict], verification_info: Optional[dict]) -> bool:
    q = (user_query or "").lower()
    verif_keywords = [
        "verify", "verification", "3-way", "4-way", "three-way", "four-way", "compare",
        "match", "failed", "flagged", "discrepanc", "mismatch", "variance", "why was", "why is",
        "why were", "paid", "difference", "reconcil", "error", "issue"
    ]
    if any(k in q for k in verif_keywords) and verification_info and (verification_info.get("checks") or verification_info.get("verdict") or verification_info.get("discrepancies")):
        return True
    if plan:
        if plan.get("verification_required") is True:
            return True
        if plan.get("intent") in ("comparison", "verification", "full_audit", "investigation"):
            return True
    return False


def _synthesize_answer(
    user_query: str,
    evidence: dict,
    plan: Optional[dict] = None,
    verification_info: Optional[dict] = None,
    bundle_id: Optional[str] = None,
    validation_result: Optional[dict] = None
) -> str:
    """Synthesize plain-English QA answer via local Ollama strictly grounded in dynamically prepared evidence & verification results."""
    synth_start = time.time()
    is_verif = _is_verification_query(user_query, plan, verification_info)

    # 1. Dynamic Context Preparation based on Intent and Query Requirements
    deterministic_verif_report = ""
    if is_verif and verification_info:
        deterministic_verif_report = _format_deterministic_verification_response(evidence, verification_info, bundle_id, user_query)

    # 2. Eliminate redundant evidence: only include document data needed for the query
    filtered_evidence = _filter_evidence_for_prompt(user_query, evidence, plan)
    logger.info(f"[QueryAgent] Filtered evidence: {json.dumps(filtered_evidence)}")

    # Check if user specifically requested line item details or unsummarized fields
    q_lower = (user_query or "").lower()
    needs_line_items = any(k in q_lower for k in ["line item", "itemized", "items ordered", "items received", "each item", "breakdown of items"])

    # Check deterministic clean status
    is_clean_verif = False
    if verification_info:
        v_checks = verification_info.get("checks") or []
        v_discs = verification_info.get("discrepancies") or []
        v_verdict = (verification_info.get("verdict") or "").lower()
        v_risk = float(verification_info.get("risk_score") or 0.0)
        v_failed = sum(1 for c in v_checks if (c.get("status") or "").lower() == "fail")
        is_clean_verif = (v_verdict in ("clean", "verified", "pass") or v_risk == 0) and v_failed == 0 and len(v_discs) == 0

    if is_verif and deterministic_verif_report:
        system_prompt = _VERIFICATION_SYSTEM_PROMPT
        extra_context = ""
        if needs_line_items:
            extra_lines = {}
            for doc_k in ("invoice", "purchase_order", "grn"):
                if filtered_evidence.get(doc_k) and filtered_evidence[doc_k].get("line_items"):
                    extra_lines[f"{doc_k}_line_items"] = filtered_evidence[doc_k]["line_items"]
            if extra_lines:
                extra_context = f"\n\nRequested Line Items:\n{json.dumps(extra_lines, indent=2)}"

        clean_mandate = ""
        if is_clean_verif and any(k in q_lower for k in ["flagged", "failed", "why was", "why is", "why were", "issue", "discrepanc", "wrong", "reject", "anomaly"]):
            clean_mandate = (
                "\n\nCRITICAL MANDATE: The user's question asks why this was flagged or failed, but the authoritative deterministic verification result is CLEAN (Risk Score: 0/100, 0 discrepancies, all checks passed). "
                "You MUST begin your response by explicitly stating that the transaction/invoice was NOT flagged. "
                "Do NOT write 'was flagged because all checks passed' or 'was flagged due to passing checks'. "
                "State clearly: The item was NOT flagged. All 3-way/4-way verification checks passed clean with zero discrepancies."
            )

        mismatch_mandate = ""
        if validation_result and validation_result.get("has_mismatch"):
            det_exp = validation_result.get("deterministic_explanation") or ""
            mismatch_items = "; ".join(validation_result.get("mismatch_aspects") or [])
            matching_items = "; ".join(validation_result.get("matching_aspects") or [])
            mismatch_mandate = (
                f"\n\nCRITICAL DETERMINISTIC ENTITY VALIDATION RESULT:\n"
                f"{det_exp}\n"
                f"- Flagged Discrepancy: {mismatch_items}\n"
                f"- Matching Details: {matching_items}\n\n"
                f"MANDATORY INSTRUCTIONS:\n"
                f"1. You MUST explicitly state in the opening sentence that the retrieved invoice/purchase was issued by '{validation_result.get('actual_vendor')}', NOT '{validation_result.get('requested_vendor')}'.\n"
                f"2. You MUST NEVER state or imply that '{validation_result.get('requested_vendor')}' issued the invoice or is the vendor.\n"
                f"3. You MUST NEVER equate or combine the requested vendor and actual vendor (e.g. do not say '{validation_result.get('requested_vendor')} (vendor name: {validation_result.get('actual_vendor')})').\n"
                f"4. Clearly distinguish the matching evidence ({matching_items}) from the mismatching vendor name ({mismatch_items}).\n"
                f"5. Explicitly state that no records or invoices exist for '{validation_result.get('requested_vendor')}'."
            )

        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Authoritative Deterministic Verification Results (SOURCE OF TRUTH):\n{deterministic_verif_report}{extra_context}\n\n"
            f"Provide a complete, factually grounded answer directly answering the user's question using the authoritative verification findings above. "
            f"State what was verified, exact amounts in ₹, exact document references (e.g. Invoice #200003 without truncation), and any discrepancies or failure reasons clearly. "
            f"Accurately distinguish the vendor/seller from the buyer/customer (Bill To). "
            f"If the user asks why an item was flagged or failed but all verification checks passed with 0 risk score, explicitly correct the premise and explain the clean verification. "
            f"If no failure reason or discrepancy exists in the retrieved evidence, state that clearly and do not invent any reasons.{clean_mandate}{mismatch_mandate}"
        )

        # Dynamic token budget based on query requirements
        if any(k in q_lower for k in ["full report", "detailed report", "detailed", "all check", "every check", "audit report", "full audit"]):
            max_tokens = 1000
        elif any(k in q_lower for k in ["why was", "why is", "why were", "flagged", "failed", "investigat", "discrepan", "variance", "mismatch", "reconcil", "reason"]):
            max_tokens = 750
        else:
            max_tokens = 750
    else:
        intent = plan.get("intent", "lookup") if plan else "lookup"
        system_prompt = _build_intent_system_prompt(intent)
        evidence_json = json.dumps(filtered_evidence, indent=2)

        clean_mandate = ""
        if is_clean_verif and any(k in q_lower for k in ["flagged", "failed", "why was", "why is", "why were", "issue", "discrepanc", "wrong", "reject", "anomaly"]):
            clean_mandate = (
                "\n\nCRITICAL MANDATE: The user's question asks why this was flagged or failed, but the authoritative deterministic verification result is CLEAN (Risk Score: 0/100, 0 discrepancies, all checks passed). "
                "You MUST begin your response by explicitly stating that the transaction/invoice was NOT flagged. "
                "Do NOT write 'was flagged because ...'. "
                "State clearly: The item was NOT flagged. All 3-way/4-way verification checks passed clean with zero discrepancies."
            )

        mismatch_mandate = ""
        if validation_result and validation_result.get("has_mismatch"):
            det_exp = validation_result.get("deterministic_explanation") or ""
            mismatch_items = "; ".join(validation_result.get("mismatch_aspects") or [])
            matching_items = "; ".join(validation_result.get("matching_aspects") or [])
            mismatch_mandate = (
                f"\n\nCRITICAL DETERMINISTIC ENTITY VALIDATION RESULT:\n"
                f"{det_exp}\n"
                f"- Flagged Discrepancy: {mismatch_items}\n"
                f"- Matching Details: {matching_items}\n\n"
                f"MANDATORY INSTRUCTIONS:\n"
                f"1. You MUST explicitly state in the opening sentence that the retrieved invoice/purchase was issued by '{validation_result.get('actual_vendor')}', NOT '{validation_result.get('requested_vendor')}'.\n"
                f"2. You MUST NEVER state or imply that '{validation_result.get('requested_vendor')}' issued the invoice or is the vendor.\n"
                f"3. You MUST NEVER equate or combine the requested vendor and actual vendor (e.g. do not say '{validation_result.get('requested_vendor')} (vendor name: {validation_result.get('actual_vendor')})').\n"
                f"4. Clearly distinguish the matching evidence ({matching_items}) from the mismatching vendor name ({mismatch_items}).\n"
                f"5. Explicitly state that no records or invoices exist for '{validation_result.get('requested_vendor')}'."
            )

        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Evidence Table:\n{evidence_json}\n\n"
            f"Provide a complete, factually grounded answer directly answering the question using only the verified evidence above.\n"
            f"Grounding guidelines:\n"
            f"- Accurately distinguish the vendor/seller who issued the invoice from the customer/buyer ('Bill To' party) who placed the order.\n"
            f"- If the company in the query is the customer/buyer (e.g. TECHGURUPLUS SOLUTIONS PVT LTD), explain this distinction accurately without claiming the customer is absent.\n"
            f"- Preserve exact document numbers (e.g. Invoice #200003; do NOT truncate or alter digits to 20000) and exact amounts (e.g. ₹4,24,800.00 total, ₹360,000.00 subtotal, ₹64,800.00 tax).\n"
            f"- Do not generate contradictory statements.{clean_mandate}{mismatch_mandate}"
        )
        max_tokens = 450

    logger.info(f"[QueryAgent] Dynamic output budget: {max_tokens} tokens for query: '{user_query}'")

    # ── 1. Call Ollama (local qwen2.5:3b) ───────────────────────────────────
    if settings.OLLAMA_HOST:
        try:
            ollama_model = settings.OLLAMA_MODEL or "qwen2.5:3b"
            payload = {
                "model": ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.1,
                    "num_ctx": 4096,
                },
            }
            client = _get_query_http_client()
            res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
            if res.status_code == 200:
                resp_data = res.json()
                raw = resp_data.get("response", "").strip()
                prompt_chars = len(system_prompt) + len(user_prompt)
                prompt_tokens = resp_data.get("prompt_eval_count") or (prompt_chars // 4)
                resp_tokens = resp_data.get("eval_count") or len(raw.split())
                synth_ms = int((time.time() - synth_start) * 1000)
                logger.info(
                    f"[QueryAgent Timing & Tokens] Prompt Chars: {prompt_chars} | "
                    f"Prompt Tokens: {prompt_tokens} | "
                    f"Response Tokens: {resp_tokens} | "
                    f"Synthesis Time: {synth_ms}ms ({synth_ms / 1000:.2f}s)"
                )
                logger.info(f"[QueryAgent] Ollama ({ollama_model}) raw response: {raw[:300]}")
                cleaned = _clean_answer_text(raw)
                cleaned = _sanitize_clean_verification_answer(cleaned, is_clean_verif)
                cleaned = _sanitize_entity_mismatch_answer(cleaned, validation_result)
                REFUSAL_PATTERNS = [
                    "not available in the retrieved evidence",
                    "i cannot answer",
                    "i don't have",
                    "information is not available",
                    "no information provided",
                    "cannot determine",
                ]
                is_refusal = any(p in cleaned.lower() for p in REFUSAL_PATTERNS)
                if cleaned and not is_refusal:
                    logger.info("[QueryAgent] Using Ollama LLM answer")
                    return cleaned
        except Exception as exc:
            logger.warning(f"[QueryAgent] Ollama synthesis error: {exc}")

    # ── 2. Fallback to OpenRouter if key is set and valid ─────────────────
    api_key = settings.OPENROUTER_API_KEY or ""
    if api_key and not api_key.startswith("your_"):
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Audit QA Answer",
            }
            payload = {
                "model": settings.OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
            client = _get_query_http_client()
            res = client.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=headers, json=payload)
            if res.status_code == 200:
                resp_json = res.json()
                choices = resp_json.get("choices", [])
                if choices:
                    msg = choices[0].get("message") or {}
                    raw = (msg.get("content") or "").strip()
                    if raw:
                        cleaned = _clean_answer_text(raw)
                        cleaned = _sanitize_clean_verification_answer(cleaned, is_clean_verif)
                        cleaned = _sanitize_entity_mismatch_answer(cleaned, validation_result)
                        if cleaned:
                            logger.info("[QueryAgent] Using OpenRouter LLM answer")
                            return cleaned
        except Exception as exc:
            logger.warning(f"[QueryAgent] OpenRouter synthesis error: {exc}")

    # ── 3. Deterministic Source-of-Truth Fallback ───────────────────────────
    if validation_result and validation_result.get("has_mismatch") and validation_result.get("deterministic_explanation"):
        logger.info("[QueryAgent] Returning deterministic entity mismatch explanation")
        return validation_result["deterministic_explanation"]

    if is_verif and deterministic_verif_report:
        logger.info("[QueryAgent] Returning deterministic fallback summary")
        inv = evidence.get("invoice") or {}
        po = evidence.get("purchase_order") or {}
        grn = evidence.get("grn") or {}
        st = verification_info.get("overall_status", "COMPLETED")
        return f"Deterministic Verification Status: {st}. Invoice {inv.get('invoice_number', 'N/A')}, PO {po.get('po_number', 'N/A')}, and GRN {grn.get('grn_number', 'N/A')} were analyzed against 3-way matching rules."

    logger.warning("[QueryAgent] LLM generation unavailable — returning deterministic template answer")
    template_facts = _build_template_answer(user_query, evidence, plan, validation_result)
    if is_verif and verification_info and verification_info.get("verdict"):
        verdict_str = verification_info.get("verdict", "").upper()
        return f"Deterministic Verification Verdict: {verdict_str}\n\n{template_facts}"
    return template_facts


def _fetch_status_bundles(db, query_filters: Optional[dict] = None, allowed_bundle_ids: Optional[List[str]] = None) -> List[dict]:
    """Fetch bundle status rows from DB for system status queries, scoped to authorized bundles."""
    try:
        q = db.query(AuditBundle)
        if allowed_bundle_ids is not None:
            q = q.filter(AuditBundle.bundle_id.in_(allowed_bundle_ids))
        if query_filters and "status" in query_filters:
            q = q.filter(AuditBundle.status == query_filters["status"])
        bundles = q.order_by(AuditBundle.created_at.desc()).limit(50).all()


        rows = []
        for b in bundles:
            vrun = (
                db.query(VerificationRun)
                .filter(VerificationRun.bundle_id == b.bundle_id)
                .order_by(VerificationRun.started_at.desc())
                .first()
            )
            failed_checks = []
            risk_score = 0.0
            overall_status = b.status or "unknown"
            verdict = "clean"

            if vrun:
                risk_score = float(vrun.overall_risk_score or 0)
                vrun_status = vrun.overall_status or ""
                if vrun_status in ("anomaly", "critical", "flagged"):
                    overall_status = "flagged"
                    verdict = "anomaly"
                elif vrun_status == "clean":
                    overall_status = "clean"
                    verdict = "clean"

                failed = (
                    db.query(VerificationCheck)
                    .filter(
                        VerificationCheck.run_id == vrun.run_id,
                        VerificationCheck.status.in_(["fail", "warning"]),
                    )
                    .all()
                )
                failed_checks = [
                    {
                        "check_name": c.check_name or c.check_type,
                        "check_type": c.check_type or c.check_name,
                        "explanation": c.explanation,
                        "variance": str(c.variance) if c.variance is not None else None,
                    }
                    for c in failed
                ]

                discs = db.query(Discrepancy).filter(Discrepancy.run_id == vrun.run_id).all()
                discrepancies_list = [
                    {
                        "category": d.category,
                        "description": d.description,
                        "severity": d.severity,
                        "recommended_action": d.recommended_action,
                    }
                    for d in discs
                ]

            rows.append({
                "bundle_id": str(b.bundle_id),
                "txn_reference": b.txn_reference,
                "status": overall_status,
                "overall_status": overall_status,
                "verdict": verdict,
                "risk_score": risk_score,
                "failed_checks": failed_checks,
                "discrepancies": discrepancies_list,
            })
        return rows
    except Exception as exc:
        logger.warning(f"[QueryAgent] Status bundle fetch error: {exc}")
        return []


def _synthesize_status_answer(user_query: str, bundles_list: List[dict]) -> str:
    """Generate concise natural language summary for multi-bundle/status queries."""
    q_lower = (user_query or "").lower()
    total_bundles = len(bundles_list)
    flagged_bundles = [b for b in bundles_list if b.get("overall_status") == "flagged" or b.get("risk_score", 0) > 0 or b.get("failed_checks") or b.get("discrepancies")]

    # If asking specifically about amount mismatches or discrepancies
    if any(k in q_lower for k in ["amount mismatch", "amount mismatches", "mismatch", "discrepanc"]):
        mismatch_flagged = []
        for b in bundles_list:
            discs = b.get("discrepancies") or []
            failed = b.get("failed_checks") or []
            amt_items = [d.get("description") for d in discs if "amount" in (d.get("category") or "").lower() or "amount" in (d.get("description") or "").lower() or "total" in (d.get("description") or "").lower()]
            for f in failed:
                if any(k in (f.get("check_name") or "").lower() for k in ["amount", "total", "subtotal", "arithmetic", "tax"]):
                    exp = f.get("explanation") or f.get("check_name")
                    if exp and exp not in amt_items:
                        amt_items.append(exp)
            if amt_items:
                mismatch_flagged.append((b, amt_items))

        if mismatch_flagged:
            lines = [f"Found {len(mismatch_flagged)} bundle(s) with amount mismatches:"]
            for b, items in mismatch_flagged:
                item_str = "; ".join(items)
                lines.append(f"- Transaction {b.get('txn_reference') or b.get('bundle_id')}: {item_str}")
            return "\n".join(lines)
        else:
            return "No amount mismatches were found across the evaluated audit bundles."

    if "flagged" in q_lower or "high risk" in q_lower or "critical" in q_lower:
        if flagged_bundles:
            lines = [f"Found {len(flagged_bundles)} flagged audit bundle(s) requiring review:"]
            for b in flagged_bundles:
                fails = b.get("failed_checks") or []
                fail_summary = ", ".join(f.get("check_name") for f in fails[:3]) if fails else "Risk score elevated"
                lines.append(f"- Transaction {b.get('txn_reference') or b.get('bundle_id')} (Risk: {int(b.get('risk_score', 0))}/100): {fail_summary}")
            return "\n".join(lines)
        else:
            return "All audit bundles are currently clean with zero flagged discrepancies."

    return f"Found {total_bundles} audit bundle(s) in the system ({len(flagged_bundles)} flagged for audit review)."


def _is_status_query(user_query: str, retrieval_plan: Optional[dict], bundle_id: Optional[str]) -> bool:
    """
    Determine if this is a genuine system-wide bundle status / cross-bundle query.
    """
    if bundle_id:
        return False

    # If the retrieval plan identified a specific bundle or document reference, it is NOT a status query
    if retrieval_plan:
        bundle_ref = retrieval_plan.get("bundle_reference")
        if bundle_ref and isinstance(bundle_ref, str) and bundle_ref.strip() and bundle_ref.strip().lower() not in ("none", "null"):
            return False

    # If specific domain entity tokens (TXN, INV, PO, GRN, UUID, etc.) exist in the query, it is NOT a cross-bundle status query
    from app.services.entity_resolver import extract_potential_entities
    if extract_potential_entities(user_query):
        return False

    q = (user_query or "").lower().strip()
    status_phrases = [
        "all bundles", "show bundles", "list bundles", "bundles are",
        "which bundles", "how many bundles", "show all", "list all",
        "system status", "overview", "all amount mismatches",
        "show me all", "all discrepancies", "all flagged", "flagged bundles",
        "flagged transactions"
    ]
    return any(k in q for k in status_phrases)


def _build_structured_verification_summary(
    evidence: dict,
    verification_info: dict,
    bundle_id: Optional[str] = None,
    llm_answer: Optional[str] = None,
    db = None,
    required_documents: Optional[List[str]] = None,
    validation_result: Optional[dict] = None,
) -> Optional[dict]:
    if not verification_info or not verification_info.get("checks"):
        return None

    checks = verification_info.get("checks") or []
    discrepancies = verification_info.get("discrepancies") or []
    verdict = verification_info.get("verdict")
    risk_score = float(verification_info.get("risk_score") or 0.0)
    overall_status = verification_info.get("overall_status") or _determine_overall_status(verdict, checks, risk_score)

    if validation_result and validation_result.get("has_mismatch"):
        overall_status = "MISMATCH"
        verdict = "MISMATCH"

    passed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "pass")
    failed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "fail")
    warning_count = sum(1 for c in checks if (c.get("status") or "").lower() == "warning")
    disc_count = len(discrepancies) if discrepancies else (failed_count + warning_count)

    # Ensure canonical evidence has all documents for complete financial & match reporting
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    bank = evidence.get("bank_statement") or {}

    if db and bundle_id and (not inv or not po or not grn or not bank):
        try:
            from app.agents.search_agent import _fetch_bundle_evidence
            full_evidence = _fetch_bundle_evidence(db, bundle_id, {"required_documents": ["invoice", "purchase_order", "grn", "bank_statement"], "required_fields": "all"})
            if not inv and full_evidence.get("invoice"):
                inv = full_evidence["invoice"]
            if not po and full_evidence.get("purchase_order"):
                po = full_evidence["purchase_order"]
            if not grn and full_evidence.get("grn"):
                grn = full_evidence["grn"]
            if not bank and full_evidence.get("bank_statement"):
                bank = full_evidence["bank_statement"]
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error filling canonical evidence in verification summary: {exc}")

    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "N/A"

    paid_amt = None
    inv_num = str(inv.get("invoice_number") or "").strip()
    if bank.get("transactions") and isinstance(bank.get("transactions"), list) and len(bank.get("transactions")) > 0:
        txns = bank.get("transactions")
        matched_txn = next(
            (t for t in txns if inv_num and (inv_num.lower() in (t.get("extracted_invoice_number") or "").lower() or inv_num.lower() in (t.get("description") or "").lower())),
            None
        )
        if not matched_txn:
            matched_txn = next((t for t in txns if (t.get("debit") or t.get("debit_amount") or 0) > 0), txns[0])
        if matched_txn:
            paid_amt = matched_txn.get("amount") or matched_txn.get("debit_amount") or matched_txn.get("debit") or matched_txn.get("credit_amount") or matched_txn.get("credit")
    elif bank.get("payment_amount"):
        paid_amt = bank.get("payment_amount")

    financials = {
        "po_total": po.get("total_amount") or po.get("subtotal"),
        "invoice_total": inv.get("total_amount"),
        "grn_total": grn.get("total_amount"),
        "paid_amount": paid_amt,
    }

    def _match_status(check_types: List[str]) -> Dict[str, str]:
        matched = [c for c in checks if (c.get("check_type") or c.get("check_name")) in check_types]
        if not matched:
            return {"status": "not_applicable", "detail": "Not evaluated"}
        if any(c.get("status") == "fail" for c in matched):
            f_chk = next(c for c in matched if c.get("status") == "fail")
            return {"status": "fail", "detail": f_chk.get("explanation", "Discrepancy detected")}
        if any(c.get("status") == "warning" for c in matched):
            w_chk = next(c for c in matched if c.get("status") == "warning")
            return {"status": "warning", "detail": w_chk.get("explanation", "Variance warning detected")}
        return {"status": "pass", "detail": "Match verified"}

    document_matches = [
        {"label": "PO ↔ Invoice", **_match_status(["po_invoice_total_match", "po_invoice_ref_match", "po_invoice_vendor_match", "tax_rate_consistency", "invoice_arithmetic_check"])},
        {"label": "PO ↔ GRN", **_match_status(["po_grn_amount_match", "grn_qty_match", "grn_qty_short_shipment", "grn_qty_over_delivery", "grn_qty_zero_received"])},
        {"label": "Invoice ↔ GRN", **_match_status(["invoice_grn_amount_match"])},
        {"label": "Invoice ↔ Bank", **_match_status(["payment_amount_match", "payment_before_invoice_date", "payment_before_grn_date", "payment_matched_to_invoice"])},
    ]

    # Deduplicated Findings
    findings_list = []
    seen_explanations = set()
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in ("fail", "warning"):
            chk_title = _CHECK_TITLES.get(c.get("check_type") or c.get("check_name"), c.get("check_name", "Check"))
            exp = c.get("explanation") or f"{chk_title} resulted in {st}"
            if exp not in seen_explanations:
                seen_explanations.add(exp)
                findings_list.append({
                    "check_name": chk_title,
                    "status": st,
                    "severity": (c.get("severity") or "HIGH").upper(),
                    "explanation": exp,
                    "expected": c.get("expected"),
                    "actual": c.get("actual"),
                    "variance": c.get("variance")
                })

    for d in discrepancies:
        desc = d.get("description")
        if desc and desc not in seen_explanations and not any(f.get("explanation") == desc for f in findings_list):
            seen_explanations.add(desc)
            findings_list.append({
                "check_name": d.get("category", "Discrepancy").replace("_", " ").title(),
                "status": "fail" if d.get("severity") in ("critical", "high") else "warning",
                "severity": (d.get("severity") or "MEDIUM").upper(),
                "explanation": desc + (f" Action: {d.get('recommended_action')}" if d.get('recommended_action') else "")
            })

    if validation_result and validation_result.get("has_mismatch"):
        overall_status = "MISMATCH"
        verdict = "MISMATCH"
        conclusion = validation_result.get("deterministic_explanation") or conclusion
        for m_asp in validation_result.get("mismatch_aspects", []):
            findings_list.insert(0, {
                "check_name": "Entity Validation Mismatch",
                "status": "fail",
                "severity": "HIGH",
                "explanation": m_asp,
            })
    elif overall_status == "VERIFIED":
        conclusion = "The 3-way match between Invoice, Purchase Order, and GRN is fully verified and consistent with no discrepancies. The transaction is validated and approved for processing."
    elif overall_status == "FAILED":
        conclusion = "Verification failed due to discrepancies identified during deterministic multi-way matching. Payment should be held pending investigation and resolution of the noted exceptions."
    else:
        conclusion = "Verification completed with warnings. Manual audit review is recommended to reconcile the identified variances before final payment approval."

    # Fetch physical source documents strictly locked to bundle_id
    source_docs = []
    if db and bundle_id:
        try:
            source_docs = _fetch_bundle_source_documents(db, bundle_id, required_documents)
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error fetching source documents for bundle {bundle_id}: {exc}")

    # Fallback to metadata labels if DB source docs empty
    if not source_docs:
        req_set = None
        if required_documents and isinstance(required_documents, list) and len(required_documents) > 0:
            req_set = {str(d).lower().strip() for d in required_documents if isinstance(d, str)}
        if (not req_set or "invoice" in req_set) and inv.get("invoice_number"):
            source_docs.append({"label": f"Invoice {inv.get('invoice_number')}", "type": "invoice", "doc_type": "invoice", "date": inv.get("invoice_date")})
        if (not req_set or "purchase_order" in req_set or "po" in req_set) and po.get("po_number"):
            source_docs.append({"label": f"PO {po.get('po_number')}", "type": "purchase_order", "doc_type": "purchase_order", "date": po.get("po_date")})
        if (not req_set or "grn" in req_set) and grn.get("grn_number"):
            source_docs.append({"label": f"GRN {grn.get('grn_number')}", "type": "grn", "doc_type": "grn", "date": grn.get("grn_date")})
        if (not req_set or "bank_statement" in req_set or "bank" in req_set) and (bank.get("account_number") or bank.get("payment_status") or bank.get("transactions")):
            source_docs.append({"label": "Bank Statement" + (f" ({bank.get('account_number')})" if bank.get("account_number") else ""), "type": "bank_statement", "doc_type": "bank_statement", "date": None})

    formatted_checks = []
    for c in checks:
        st = (c.get("status") or "").lower()
        if st == "not_applicable":
            continue
        chk_type = c.get("check_type") or c.get("check_name") or "Check"
        title = _CHECK_TITLES.get(chk_type, chk_type.replace("_", " ").title())
        formatted_checks.append({
            "check_type": chk_type,
            "title": title,
            "status": st,
            "severity": c.get("severity"),
            "expected": c.get("expected"),
            "actual": c.get("actual"),
            "variance": c.get("variance"),
            "explanation": c.get("explanation"),
            "block_text": _format_check_block(c, evidence)
        })

    return {
        "overall_status": overall_status,
        "verdict": verdict or overall_status,
        "explanation": llm_answer or conclusion,
        "llm_answer": llm_answer,
        "risk_score": risk_score,
        "checks_passed": passed_count,
        "checks_failed": failed_count,
        "warnings_count": warning_count,
        "discrepancies_count": disc_count,
        "financials": financials,
        "document_matches": document_matches,
        "findings": findings_list,
        "conclusion": conclusion,
        "vendor_name": vendor,
        "invoice_number": inv.get("invoice_number"),
        "po_number": po.get("po_number"),
        "grn_number": grn.get("grn_number"),
        "source_documents": source_docs,
        "formatted_checks": formatted_checks,
    }


def query_node(state: BundleState) -> Dict[str, Any]:
    """LangGraph Node: QA Agent."""
    start = time.time()
    user_query = state.get("user_query") or ""
    bundle_id = state.get("bundle_id")
    evidence_table = state.get("evidence_table")
    retrieval_plan = state.get("retrieval_plan")
    query_filters = state.get("query_filters")

    logger.info(f"[QueryAgent] Answering query: '{user_query}' for bundle {bundle_id}")

    # ── CASE 0: No bundle resolved & not a status query — vendor/document not found ──
    if not bundle_id and not _is_status_query(user_query, retrieval_plan, bundle_id):
        db = SessionLocal()
        known_vendors = []
        try:
            vendors = db.query(Vendor).all()
            seen = set()
            for v in vendors:
                v_name = (v.name or v.name_normalized or "").strip()
                if v_name and v_name.lower() not in seen:
                    seen.add(v_name.lower())
                    known_vendors.append(v_name.title())
        except Exception:
            pass
        finally:
            db.close()

        vendor_hint = f" Known active vendors in the system: {', '.join(known_vendors[:5])}." if known_vendors else ""
        not_found_answer = (
            f"No matching audit bundle, invoice, purchase order, or vendor details were found for your query: \"{user_query}\".{vendor_hint} "
            f"Please verify the invoice number, PO number, or vendor name and try again."
        )
        logger.warning(f"[QueryAgent] No bundle resolved for query: '{user_query}'.")

        report_output = {
            "query": user_query,
            "query_type": "not_found",
            "answer_type": "not_found",
            "report_type": "not_found",
            "bundle_id": None,
            "bundle": None,
            "answer": not_found_answer,
            "verdict": "NOT FOUND",
            "result": {"found": False, "status": "NOT FOUND", "verdict": "NOT FOUND", "ambiguous": False, "bundle_id": None},
            "evidence": {},
            "verification_checks": [],
            "source_documents": [],
            "retrieval_plan": retrieval_plan,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"report": report_output, "answer": not_found_answer}

    # ── CASE 1: System-wide bundle status / cross-bundle query ─────────────────
    authorized_bundle_ids = state.get("authorized_bundle_ids")
    if _is_status_query(user_query, retrieval_plan, bundle_id):
        logger.info("[QueryAgent] Detected system status / cross-bundle query")
        db = SessionLocal()
        try:
            bundles_list = _fetch_status_bundles(db, query_filters, allowed_bundle_ids=authorized_bundle_ids)
        finally:
            db.close()

        status_answer = _synthesize_status_answer(user_query, bundles_list)

        report_output = {
            "query": user_query,
            "query_type": "status_query",
            "answer_type": "status_query",
            "bundle_id": None,
            "bundle": None,
            "answer": status_answer,
            "bundles": bundles_list,
            "result_count": len(bundles_list),
            "filters_applied": query_filters or {},
            "retrieval_plan": retrieval_plan,
            "source_documents": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        db = SessionLocal()
        try:
            db.add(
                AgentExecutionLog(
                    bundle_id=None,
                    agent_name="query_agent",
                    input_snapshot={"user_query": user_query, "bundle_id": None},
                    output_snapshot={"answer": status_answer, "result_count": len(bundles_list)},
                    latency_ms=int((time.time() - start) * 1000),
                    status="success",
                )
            )
            db.commit()
        except Exception as exc:
            logger.warning(f"[QueryAgent] DB log error: {exc}")
        finally:
            db.close()

        return {"report": report_output, "answer": status_answer}

    # ── CASE 2: Specific query for a resolved bundle ──────────────────────────
    if not evidence_table and bundle_id:
        db = SessionLocal()
        try:
            from app.agents.search_agent import _fetch_bundle_evidence
            evidence_table = _fetch_bundle_evidence(db, bundle_id, retrieval_plan)
        except Exception as exc:
            logger.warning(f"[QueryAgent] Error fetching evidence table: {exc}")
        finally:
            db.close()

    evidence_table = evidence_table or {}

    # Deterministic entity-grounding validation
    validation_result = validate_query_entity_grounding(user_query, evidence_table)
    if validation_result.get("has_mismatch"):
        logger.warning(
            f"[QueryAgent] Entity mismatch detected: "
            f"Requested vendor='{validation_result.get('requested_vendor')}', Actual vendor='{validation_result.get('actual_vendor')}'"
        )

    state_checks = state.get("verification_checks") or []
    state_discrepancies = state.get("discrepancies") or []
    state_verdict = state.get("verdict")
    state_severity = state.get("severity")
    state_risk_score = state.get("risk_score")

    db = SessionLocal()
    checks_list = []
    discrepancies_list = list(state_discrepancies)
    risk_score = float(state_risk_score or 0.0)
    verdict = state_verdict
    bundle_meta = None

    try:
        if bundle_id:
            bundle_obj = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
            if bundle_obj:
                bundle_meta = {
                    "bundle_id": str(bundle_obj.bundle_id),
                    "txn_reference": bundle_obj.txn_reference,
                    "status": bundle_obj.status,
                    "created_at": bundle_obj.created_at.isoformat() if bundle_obj.created_at else None,
                }

            vrun = db.query(VerificationRun).filter(VerificationRun.bundle_id == bundle_id).order_by(VerificationRun.started_at.desc()).first()
            if vrun:
                if not state_checks:
                    checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == vrun.run_id).all()
                    checks_list = [
                        {
                            "check_name": c.check_name,
                            "check_type": c.check_name,
                            "status": c.status,
                            "severity": c.severity,
                            "explanation": c.explanation,
                            "expected": c.expected_value,
                            "actual": c.actual_value,
                            "variance": str(c.variance) if c.variance is not None else None,
                        }
                        for c in checks
                    ]
                if not discrepancies_list:
                    discs = db.query(Discrepancy).filter(Discrepancy.run_id == vrun.run_id).all()
                    discrepancies_list = [
                        {
                            "description": d.description,
                            "severity": d.severity,
                            "category": d.category,
                            "recommended_action": d.recommended_action,
                        }
                        for d in discs
                    ]
                if state_risk_score is None and vrun.overall_risk_score is not None:
                    risk_score = float(vrun.overall_risk_score)
                if not verdict and vrun.overall_status:
                    verdict = "clean" if vrun.overall_status == "clean" else "anomaly"
    except Exception as exc:
        logger.warning(f"[QueryAgent] Error fetching checks from DB: {exc}")

    if state_checks and not checks_list:
        checks_list = [
            {
                "check_name": c.get("check_type", c.get("check_name", "")),
                "check_type": c.get("check_type", c.get("check_name", "")),
                "status": c.get("status"),
                "severity": c.get("severity"),
                "expected": c.get("expected"),
                "actual": c.get("actual"),
                "variance": c.get("variance"),
                "explanation": c.get("explanation"),
            }
            for c in state_checks
        ]

    verification_info = None
    if checks_list or verdict:
        verification_info = {
            "verdict": verdict,
            "severity": state_severity,
            "risk_score": risk_score,
            "checks": checks_list,
            "discrepancies": discrepancies_list,
        }

    answer = _synthesize_answer(user_query, evidence_table, retrieval_plan, verification_info, bundle_id, validation_result)
    result_metadata = _build_result_metadata(evidence_table, bundle_id, validation_result)

    # Intent normalization
    intent = "field_lookup"
    is_verif = False
    if retrieval_plan:
        raw_intent = retrieval_plan.get("intent", "lookup")
        if raw_intent in ("comparison", "verification", "full_audit"):
            intent = raw_intent
            is_verif = True
        elif raw_intent == "payment_lookup":
            intent = "payment_lookup"
        else:
            intent = "field_lookup"
        if retrieval_plan.get("verification_required") is True:
            is_verif = True

    # Fetch validated source documents strictly locked to bundle_id
    req_docs = retrieval_plan.get("required_documents") if retrieval_plan else None
    verif_summary = None
    source_docs = []
    try:
        source_docs = _fetch_bundle_source_documents(db, bundle_id, req_docs)
        if is_verif and verification_info:
            verif_summary = _build_structured_verification_summary(
                evidence=evidence_table,
                verification_info=verification_info,
                bundle_id=bundle_id,
                llm_answer=answer,
                db=db,
                required_documents=req_docs,
                validation_result=validation_result,
            )
    except Exception as exc:
        logger.warning(f"[QueryAgent] Error building verification summary: {exc}")
    finally:
        db.close()

    # Standardized response schema
    report_output = {
        "query": user_query,
        "query_type": intent,
        "answer_type": intent,
        "bundle_id": bundle_id,
        "bundle": bundle_meta,
        "answer": answer,
        "verdict": result_metadata.get("verdict", "VERIFIED"),
        "result": result_metadata,
        "entity_validation": validation_result,
        "verification_summary": verif_summary if is_verif else None,
        "financials": (verif_summary.get("financials") if verif_summary and is_verif else None),
        "document_matches": (verif_summary.get("document_matches") if verif_summary and is_verif else None),
        "findings": (verif_summary.get("findings") if verif_summary and is_verif else None),
        "detailed_checks": (verif_summary.get("formatted_checks") if verif_summary and is_verif else None),
        "source_documents": (verif_summary.get("source_documents") if verif_summary and is_verif and verif_summary.get("source_documents") else source_docs),
        "evidence": evidence_table,
        "verification_checks": checks_list if is_verif else [],
        "retrieval_plan": retrieval_plan,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    db = SessionLocal()
    try:
        db.add(
            AgentExecutionLog(
                bundle_id=bundle_id,
                agent_name="query_agent",
                input_snapshot={"user_query": user_query, "bundle_id": bundle_id},
                output_snapshot={"answer": answer},
                latency_ms=int((time.time() - start) * 1000),
                status="success",
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning(f"[QueryAgent] DB log error: {exc}")
    finally:
        db.close()

    return {"report": report_output, "answer": answer}
