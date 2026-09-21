"""
Regression tests for QueryAgent deterministic entity validation, vendor mismatch detection, and evidence grounding.
"""

import pytest
from app.agents.query_agent import (
    validate_query_entity_grounding,
    _extract_requested_vendor,
    _are_vendors_matching,
    _sanitize_entity_mismatch_answer,
    _build_result_metadata,
    _build_template_answer,
    query_node,
)


def test_extract_requested_vendor():
    # Various query formulations
    assert _extract_requested_vendor("Show me evidence for the laptop purchase from ABC Ltd") == "ABC Ltd"
    assert _extract_requested_vendor("Show evidence for laptop purchase from Murthy Oak and Palla") == "Murthy Oak and Palla"
    assert _extract_requested_vendor("Did we receive an invoice from Acme Corp for laptops?") == "Acme Corp"
    assert _extract_requested_vendor("What is the total of the invoice by XYZ Pvt Ltd?") == "XYZ Pvt Ltd"
    assert _extract_requested_vendor("Verify invoice 200005 against PO 100005") is None


def test_are_vendors_matching():
    # Matching cases
    assert _are_vendors_matching("Murthy Oak and Palla", "Murthy, Oak and Palla Pvt Ltd") is True
    assert _are_vendors_matching("Murthy Oak", "Murthy, Oak and Palla Pvt Ltd") is True
    assert _are_vendors_matching("Dell Technologies", "Dell Technologies India Pvt Ltd") is True

    # Mismatch cases
    assert _are_vendors_matching("ABC Ltd", "Murthy, Oak and Palla Pvt Ltd") is False
    assert _are_vendors_matching("Acme Corp", "Tata Consultancy Services") is False


def test_matching_vendor_grounding():
    user_query = "Show me evidence for the laptop purchase from Murthy Oak and Palla"
    evidence = {
        "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
        "invoice": {
            "invoice_number": "200003",
            "total_amount": 424800,
            "subtotal": 360000,
            "tax_amount": 64800,
            "invoice_date": "2026-05-01",
            "line_items": [{"description": "8 Dell Latitude 5440 Laptops", "qty": 8, "unit_price": 45000}]
        }
    }

    val = validate_query_entity_grounding(user_query, evidence)
    assert val["has_mismatch"] is False
    assert val["vendor_mismatch"] is False

    meta = _build_result_metadata(evidence, "test-bundle-id", val)
    assert meta["status"] == "VERIFIED"
    assert meta["verdict"] == "VERIFIED"


def test_mismatching_vendor_grounding():
    user_query = "Show me evidence for the laptop purchase from ABC Ltd"
    evidence = {
        "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
        "invoice": {
            "invoice_number": "200003",
            "total_amount": 424800,
            "subtotal": 360000,
            "tax_amount": 64800,
            "invoice_date": "2026-05-01",
            "line_items": [{"description": "8 Dell Latitude 5440 Laptops", "qty": 8, "unit_price": 45000}]
        }
    }

    val = validate_query_entity_grounding(user_query, evidence)
    assert val["has_mismatch"] is True
    assert val["vendor_mismatch"] is True
    assert val["requested_vendor"] == "ABC Ltd"
    assert val["actual_vendor"] == "Murthy, Oak and Palla Pvt Ltd"
    assert any("ABC Ltd" in item for item in val["mismatch_aspects"])
    assert any("Dell Latitude" in item for item in val["matching_aspects"])

    meta = _build_result_metadata(evidence, "test-bundle-id", val)
    assert meta["status"] == "MISMATCH"
    assert meta["verdict"] == "MISMATCH"
    assert meta["vendor_mismatch"] is True
    assert meta["requested_vendor"] == "ABC Ltd"
    assert meta["actual_vendor"] == "Murthy, Oak and Palla Pvt Ltd"

    # Fallback template answer must explain the mismatch deterministically
    ans = _build_template_answer(user_query, evidence, validation_result=val)
    assert "Murthy, Oak and Palla Pvt Ltd" in ans
    assert "ABC Ltd" in ans
    assert "Entity Mismatch" in ans


def test_invoice_number_mismatch():
    user_query = "Show me invoice 200009 from Murthy Oak"
    evidence = {
        "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
        "invoice": {
            "invoice_number": "200003",
            "total_amount": 424800,
        }
    }

    val = validate_query_entity_grounding(user_query, evidence)
    assert val["has_mismatch"] is True
    assert val["invoice_mismatch"] is True
    assert val["requested_invoice"] == "200009"
    assert val["actual_invoice"] == "200003"

    meta = _build_result_metadata(evidence, "test-bundle-id", val)
    assert meta["status"] == "MISMATCH"


def test_sanitizer_prevents_hallucinated_issuance():
    validation_result = {
        "has_mismatch": True,
        "vendor_mismatch": True,
        "requested_vendor": "ABC Ltd",
        "actual_vendor": "Murthy, Oak and Palla Pvt Ltd",
        "deterministic_explanation": "Entity Mismatch: Invoice 200003 was issued by vendor 'Murthy, Oak and Palla Pvt Ltd', not 'ABC Ltd'."
    }

    # Raw LLM hallucination matching the user screenshot
    hallucinated_text = (
        "The evidence shows that ABC Ltd (vendor name: murthy oak and palla) issued an invoice "
        "(invoice number: 200003) for the purchase of 8 Dell Latitude 5440 Laptops."
    )

    sanitized = _sanitize_entity_mismatch_answer(hallucinated_text, validation_result)
    assert "ABC Ltd issued" not in sanitized
    assert "Murthy, Oak and Palla Pvt Ltd" in sanitized


def test_query_node_mismatch_integration():
    state = {
        "user_query": "Show me evidence for the laptop purchase from ABC Ltd",
        "bundle_id": "test-bundle-uuid",
        "evidence_table": {
            "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
            "invoice": {
                "invoice_number": "200003",
                "total_amount": 424800,
                "subtotal": 360000,
                "tax_amount": 64800,
                "invoice_date": "2026-05-01",
                "line_items": [{"description": "8 Dell Latitude 5440 Laptops", "qty": 8, "unit_price": 45000}]
            }
        },
        "retrieval_plan": {
            "intent": "lookup",
            "verification_required": False,
            "report_required": False,
            "required_documents": ["invoice"]
        }
    }

    res = query_node(state)
    report = res["report"]
    assert report["result"]["status"] == "MISMATCH"
    assert report["result"]["vendor_mismatch"] is True
    assert report["result"]["requested_vendor"] == "ABC Ltd"
    assert report["result"]["actual_vendor"] == "Murthy, Oak and Palla Pvt Ltd"
    assert "Murthy, Oak and Palla" in res["answer"]


def test_customer_role_grounding():
    """
    Test Case:
    Query: 'Show me evidence for the laptop purchase from TECHGURUPLUS SOLUTIONS PVT LTD'
    Expected understanding: The invoice identifies Murthy, Oak and Palla Pvt Ltd as the seller and
    TECHGURUPLUS SOLUTIONS PVT LTD as the customer. The system explains this distinction accurately,
    preserves invoice number 200003 and total ₹4,24,800, and avoids falsely claiming the customer is absent.
    """
    user_query = "Show me evidence for the laptop purchase from TECHGURUPLUS SOLUTIONS PVT LTD"
    evidence = {
        "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
        "customer_name": "TECHGURUPLUS SOLUTIONS PVT LTD",
        "invoice": {
            "invoice_number": "200003",
            "total_amount": 424800,
            "subtotal": 360000,
            "tax_amount": 64800,
            "invoice_date": "2026-05-01",
            "vendor_name": "Murthy, Oak and Palla Pvt Ltd",
            "customer_name": "TECHGURUPLUS SOLUTIONS PVT LTD",
            "bill_to": "TECHGURUPLUS SOLUTIONS PVT LTD",
            "line_items": [{"description": "8 Dell Latitude 5440 Laptops", "qty": 8, "unit_price": 45000, "line_total": 360000}]
        }
    }

    val = validate_query_entity_grounding(user_query, evidence)
    assert val["has_mismatch"] is False
    assert val["vendor_mismatch"] is False
    assert val["is_customer_match"] is True

    meta = _build_result_metadata(evidence, "test-bundle-id", val)
    assert meta["status"] == "VERIFIED"
    assert meta["verdict"] == "VERIFIED"
    assert meta["vendor_name"] == "Murthy, Oak and Palla Pvt Ltd"
    assert meta["customer_name"] == "TECHGURUPLUS SOLUTIONS PVT LTD"
    assert meta["invoice_number"] == "200003"
    assert meta["total_amount"] == 424800

    ans = _build_template_answer(user_query, evidence, validation_result=val)
    assert "200003" in ans
    assert "Murthy, Oak and Palla Pvt Ltd" in ans
    assert "TECHGURUPLUS SOLUTIONS PVT LTD" in ans
    assert "424,800" in ans

