"""
tests/test_report_agent.py
--------------------------
Regression and unit tests for ReportAgent:
1. Proves verified monetary values (e.g. ₹130,390.00 for TXN-2026-935) remain 100% accurate
   without LLM quantization errors, truncation, or division (e.g. ₹13,039.00).
2. Proves report 'discrepancies_count' equals the number of failed verification checks (2 for TXN-2026-935).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock

from app.agents.report_agent import (
    _enforce_monetary_integrity,
    _template_narrative,
    report_detailed_node,
    report_summary_node,
)


def test_monetary_integrity_exact_and_corruptions():
    """Verify _enforce_monetary_integrity preserves exact amounts and fixes LLM 10x/scaling corruptions."""
    evidence = {
        "invoice": {"total_amount": 130390.0, "tax_amount": 19890.0},
        "purchase_order": {"total_amount": 130390.0},
        "bank_statement": {"payment_amount": 130390.0},
    }

    # Case 1: Exact amount is preserved
    exact_text = "The invoice total is ₹130,390.00 and payment was made on 2026-05-03."
    out = _enforce_monetary_integrity(exact_text, evidence)
    assert "130,390.00" in out

    # Case 2: 10x lower quantization error (Rs. 13,039 or ₹13,039.00)
    corrupted_10x_lower = "The payment of Rs. 13,039.00 was recorded before the invoice date. Total amount was ₹13,039."
    out = _enforce_monetary_integrity(corrupted_10x_lower, evidence)
    assert "130,390.00" in out
    assert "13,039" not in out

    # Case 3: 10x higher / Indian numbering error (Rs. 13,03,900)
    corrupted_10x_higher = "Payment of Rs. 13,03,900 was processed on 2026-05-03."
    out = _enforce_monetary_integrity(corrupted_10x_higher, evidence)
    assert "130,390.00" in out
    assert "13,03,900" not in out

    # Case 4: Multiple financial fields in same narrative (Total + Tax)
    multi_text = "Invoice total was Rs. 13039.00 with tax of Rs. 1989.00."
    out = _enforce_monetary_integrity(multi_text, evidence)
    assert "130,390.00" in out
    assert "19,890.00" in out


def test_template_narrative_formatting():
    """Verify _template_narrative accurately formats verified amounts."""
    evidence = {
        "invoice": {"invoice_number": "200001", "total_amount": 130390.0, "invoice_date": "2026-05-08"},
        "purchase_order": {"po_number": "100001", "total_amount": 130390.0},
        "grn": {"grn_number": "300001", "grn_date": "2026-05-09"},
        "bank_statement": {"payment_status": "confirmed", "payment_date": "2026-05-03", "payment_amount": 130390.0, "bank_reference": "TXN935"},
        "vendor": "Acme Industrial",
    }
    checks = [
        {"check_type": "payment_before_invoice_date", "status": "fail", "expected": ">= 2026-05-08", "actual": "2026-05-03", "explanation": "Payment precedes invoice date"},
        {"check_type": "payment_before_grn_date", "status": "fail", "expected": ">= 2026-05-09", "actual": "2026-05-03", "explanation": "Payment precedes GRN date"},
    ]
    discrepancies = [
        {"category": "date_sequence", "severity": "high", "description": "Payment precedes invoice date", "recommended_action": "Investigate"},
        {"category": "date_sequence", "severity": "high", "description": "Payment precedes GRN date", "recommended_action": "Investigate"},
    ]

    narrative = _template_narrative("TXN-2026-935", checks, discrepancies, evidence)
    assert "130,390.00" in narrative
    assert "13,039" not in narrative
    assert "Acme Industrial" in narrative


def test_txn_2026_935_report_detailed_regression():
    """
    Regression test for TXN-2026-935:
    - 15 total checks, 13 passed, 2 failed
    - Actual verified payment & invoice amount: ₹130,390.00
    - Discrepancies count must be 2 (equal to failed verification checks)
    - Narrative must maintain ₹130,390.00 with 100% fidelity even if LLM returned 13,039.
    """
    checks = [
        {"check_type": "po_invoice_match", "status": "pass", "severity": "low"},
        {"check_type": "po_vendor_match", "status": "pass", "severity": "low"},
        {"check_type": "invoice_vendor_match", "status": "pass", "severity": "low"},
        {"check_type": "line_item_qty_match", "status": "pass", "severity": "low"},
        {"check_type": "line_item_unit_price_match", "status": "pass", "severity": "low"},
        {"check_type": "subtotal_math_check", "status": "pass", "severity": "low"},
        {"check_type": "tax_math_check", "status": "pass", "severity": "low"},
        {"check_type": "total_amount_math_check", "status": "pass", "severity": "low"},
        {"check_type": "grn_po_ref_match", "status": "pass", "severity": "low"},
        {"check_type": "grn_item_match", "status": "pass", "severity": "low"},
        {"check_type": "bank_invoice_ref_match", "status": "pass", "severity": "low"},
        {"check_type": "bank_amount_match", "status": "pass", "severity": "low"},
        {"check_type": "grn_received_condition", "status": "pass", "severity": "low"},
        {"check_type": "payment_before_invoice_date", "status": "fail", "expected": ">= 2026-05-08", "actual": "2026-05-03", "explanation": "Payment precedes invoice date", "severity": "high"},
        {"check_type": "payment_before_grn_date", "status": "fail", "expected": ">= 2026-05-09", "actual": "2026-05-03", "explanation": "Payment precedes GRN date", "severity": "high"},
    ]

    discrepancies = [
        {"category": "date_sequence", "severity": "high", "description": "Payment recorded 2026-05-03 before invoice date 2026-05-08.", "recommended_action": "Check for backdated invoice."},
        {"category": "date_sequence", "severity": "high", "description": "Payment recorded 2026-05-03 before goods receipt confirmed on 2026-05-09.", "recommended_action": "Confirm delivery before payment authorization."},
    ]

    mock_evidence = {
        "bundle_id": "test-bundle-935",
        "invoice": {
            "invoice_number": "200001",
            "invoice_date": "2026-05-08",
            "total_amount": 130390.0,
            "tax_amount": 19890.0,
            "vendor_name": "Test Vendor",
        },
        "purchase_order": {
            "po_number": "100001",
            "po_date": "2026-05-01",
            "total_amount": 130390.0,
        },
        "grn": {
            "grn_number": "300001",
            "grn_date": "2026-05-09",
        },
        "bank_statement": {
            "payment_status": "confirmed",
            "payment_date": "2026-05-03",
            "payment_amount": 130390.0,
            "bank_reference": "TXN935",
        },
        "vendor": "Test Vendor",
    }

    state = {
        "bundle_id": "test-bundle-935",
        "verdict": "flagged",
        "severity": "high",
        "risk_score": 40.0,
        "verification_checks": checks,
        "discrepancies": discrepancies,
    }

    # Simulate LLM returning a corrupted narrative with 10x lower amount (Rs. 13,039.00)
    flawed_llm_response = (
        "Audit Narrative:\n"
        "Payment of Rs. 13,039.00 was made on May 3, 2026 before invoice date May 8, 2026 "
        "and before GRN date May 9, 2026. Total invoice amount was Rs. 13,039.00."
    )

    with patch("app.agents.report_agent._get_bundle_evidence", return_value=mock_evidence), \
         patch("app.agents.report_agent._generate_narrative", return_value=flawed_llm_response), \
         patch("app.agents.report_agent._persist_report", return_value="report-id-123"), \
         patch("app.agents.report_agent.SessionLocal") as mock_db:

        mock_db_instance = MagicMock()
        mock_db.return_value = mock_db_instance

        res = report_detailed_node(state)
        report = res["report"]

        # 1. Discrepancies count must equal failed verification checks (2 issues)
        assert report["discrepancies_count"] == 2
        assert len(report["failed_checks"]) == 2
        assert report["checks_passed"] == 13
        assert report["checks_total"] == 15
        assert report["risk_score"] == 40.0

        # 2. Monetary integrity: 130,390 is restored and 13,039 is eliminated
        narrative = report["narrative"]
        assert "130,390.00" in narrative
        assert "13,039" not in narrative
