import pytest
from app.agents.query_agent import (
    _format_deterministic_verification_response,
    _synthesize_answer,
    _is_verification_query,
    _format_amount,
    _get_quantity_summary,
)

def test_format_amount():
    assert _format_amount(637200) == "₹637,200"
    assert _format_amount("637200.50") == "₹637,200.50"
    assert _format_amount(None) == "N/A"

def test_get_quantity_summary_matched():
    evidence = {
        "purchase_order": {"line_items": [{"description": "Switch", "qty": 19}]},
        "grn": {"line_items": [{"description": "Switch", "qty_received": 19}]}
    }
    summary = _get_quantity_summary(evidence)
    assert summary == "19 units (Matched)"

def test_get_quantity_summary_mismatched():
    evidence = {
        "purchase_order": {"line_items": [{"description": "Switch", "qty": 19}]},
        "grn": {"line_items": [{"description": "Switch", "qty_received": 17}]}
    }
    summary = _get_quantity_summary(evidence)
    assert "PO: 19 units" in summary
    assert "GRN: 17 units" in summary
    assert "Difference: 2 units" in summary

def test_format_deterministic_verification_response_structure():
    evidence = {
        "vendor_name": "Oak PLC Traders",
        "invoice": {
            "invoice_number": "INV-200005",
            "po_number": "PO-100005",
            "total_amount": 637200.0,
            "subtotal": 540000.0,
            "tax_amount": 97200.0,
            "invoice_date": "2026-05-10",
        },
        "purchase_order": {
            "po_number": "PO-100005",
            "total_amount": 637200.0,
            "subtotal": 540000.0,
            "tax_rate": 18.0,
            "po_date": "2026-05-01",
            "line_items": [{"description": "Networking Switch", "qty": 19}]
        },
        "grn": {
            "grn_number": "GRN-2026-0005",
            "total_amount": 540000.0,
            "grn_date": "2026-05-05",
            "line_items": [{"description": "Networking Switch", "qty_received": 17}]
        }
    }

    verification_info = {
        "verdict": "anomaly",
        "severity": "critical",
        "risk_score": 30.0,
        "checks": [
            {
                "check_type": "po_invoice_total_match",
                "status": "pass",
                "expected": "637200.00",
                "actual": "637200.00",
                "explanation": "PO and Invoice totals match"
            },
            {
                "check_type": "po_invoice_vendor_match",
                "status": "pass",
                "expected": "Oak PLC Traders",
                "actual": "Oak PLC Traders",
                "explanation": "Vendor names match"
            },
            {
                "check_type": "grn_qty_short_shipment",
                "status": "fail",
                "expected": "19",
                "actual": "17",
                "variance": "2",
                "severity": "critical",
                "explanation": "Short shipment on Networking Switch: ordered 19, received 17"
            }
        ],
        "discrepancies": [
            {
                "description": "Short shipment: 2 units of Networking Switch not received.",
                "severity": "critical",
                "recommended_action": "Chase outstanding delivery or reject partial invoice payment."
            }
        ]
    }

    resp = _format_deterministic_verification_response(evidence, verification_info, "bundle-123", user_query="all checks")

    # Verify all required sections and data points exist
    assert "Deterministic Verification Findings (SOURCE OF TRUTH)" in resp
    assert "Overall Status: FAILED" in resp
    assert "Invoice: INV-200005" in resp
    assert "Purchase Order: PO-100005" in resp
    assert "GRN: GRN-2026-0005" in resp
    assert "Vendor: Oak PLC Traders" in resp
    assert "Invoice: INV-200005 (Total: ₹637,200" in resp
    assert "Purchase Order: PO-100005 (Total: ₹637,200" in resp
    assert "GRN: GRN-2026-0005 (Total: ₹540,000" in resp
    assert "Checks Passed: 2" in resp
    assert "Checks Failed: 1" in resp
    assert "Risk Score: 30/100" in resp

    assert "### Relevant Checks:" in resp
    assert "PO ↔ Invoice Amount Match" in resp
    assert "PO Gross Total: ₹637,200" in resp
    assert "Invoice Gross Total: ₹637,200" in resp
    assert "Result: PASS" in resp

    assert "Short Shipment (GRN Qty < PO Qty)" in resp
    assert "PO Ordered Qty: 19 units" in resp
    assert "GRN Received Qty: 17 units" in resp
    assert "Difference: 2 units" in resp
    assert "Result: FAIL" in resp

    assert "### Discrepancies & Findings:" in resp
    assert "Short shipment" in resp

def test_is_verification_query():
    assert _is_verification_query("Verify invoice 200005 against PO 100005 and GRN-2026-0005", {"intent": "comparison", "verification_required": True}, {}) is True
    assert _is_verification_query("What is the total amount of Invoice 200005?", {"intent": "lookup", "verification_required": False}, {}) is False
