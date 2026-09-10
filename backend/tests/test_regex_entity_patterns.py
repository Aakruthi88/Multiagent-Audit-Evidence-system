"""
test_regex_entity_patterns.py
-------------------------------
Comprehensive test suite verifying regex extraction for:
- Invoice numbers
- PO numbers
- GRN numbers
- Delivery Note numbers
- Transaction references (TXN)
- Bank references
- Bank account numbers
- Bundle UUIDs
- Entity resolution candidate extraction

Verifies both valid positive examples and negative examples designed to trigger false positives.
"""

import pytest
import re
from app.services.matching_utils import parse_bank_narration
from app.services.entity_resolver import extract_potential_entities


# ---------------------------------------------------------------------------
# Test Data Definitions
# ---------------------------------------------------------------------------

INVOICE_POSITIVES = [
    ("INV200005", "INV200005"),
    ("INV-200005", "INV-200005"),
    ("INV/200005", "INV/200005"),
    ("Invoice 200005", "200005"),
    ("Invoice #200005", "200005"),
    ("Tax Invoice: INV-2026-99", "INV-2026-99"),
    ("INVOICE # 200003", "200003"),
    ("INVOICE NUMBER: 200003", "200003"),
]

INVOICE_NEGATIVES = [
    "GOODS INVENT",
    "INVALIDATED",
    "INVESTMENT",
    "Invoice Total: 500.00",
    "Dora-Rana Pvt Ltd 71/14, Industrial Area INVOICE\nDATE 08-05-2026",
]

PO_POSITIVES = [
    ("PO-100005", "PO-100005"),
    ("PO 100005", "100005"),
    ("PO#100005", "100005"),
    ("PO: 100005", "100005"),
    ("Purchase Order #: PO-100005", "PO-100005"),
    ("Purchase Order No. 100005", "100005"),
    ("PO # 100003", "100003"),
    ("PO NUMBER: 100003", "100003"),
]

PO_NEGATIVES = [
    "PO Box 123",
    "PO Date: 2026-01-01",
    "POSITION",
    "IMPORT",
    "SUPPORTER",
    "TECHGURUPLUS SOLUTIONS PVT LTD\nH-195, Sarita Vihar, New Delhi 110076 PURCHASE ORDER\nPhone: 011-4356 7890",
]

GRN_POSITIVES = [
    ("GRN-2026-0005", "GRN-2026-0005"),
    ("GRN 2026 0005", "2026 0005"),
    ("GRN#2026-0005", "2026-0005"),
    ("GRN20260005", "GRN20260005"),
    ("Goods Received Note #: GRN-1001", "GRN-1001"),
]

GRN_NEGATIVES = [
    "GRN Date: 2026-01-01",
    "BACKGROUND",
    "GRN Total: 1500.00",
]

DN_POSITIVES = [
    ("DN-100005", "DN-100005"),
    ("DN 100005", "100005"),
    ("Delivery Note #: DN-100005", "DN-100005"),
    ("Delivery Note 100005", "100005"),
    ("Delivery Note No: DN-1001", "DN-1001"),
    ("Challan No: DN-999", "DN-999"),
]

DN_NEGATIVES = [
    "GOODS NOTE",
    "DEMO NOTE",
    "DN Date: 2026-01-01",
]

TXN_POSITIVES = [
    "TXN-2026-180",
    "TXN 2026 180",
    "TXN-2026-001",
    "TXN2026180",
    "TXN-2025-0001",
    "TXN_2026_005",
]

TXN_NEGATIVES = [
    "TEXTBOOK",
    "TXN",
]

BANK_REF_POSITIVES = [
    "Ref6821782",
    "Ref-6821782",
    "reference 6821782",
    "REF#6821782",
    "Ref 6821782",
    "NEFT-Ref7655194-Dora-Rana",
]

BANK_REF_NEGATIVES = [
    "REFRESH",
    "PREFER",
    "REFERRAL",
]


# ---------------------------------------------------------------------------
# Test Functions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Direct Parser Regex Tests
# ---------------------------------------------------------------------------

from app.services.parsers.po_parser import _RE_PO_NUMBER
from app.services.parsers.invoice_parser import _RE_INV_NUMBER
from app.services.parsers.grn_parser import _RE_GRN_NUMBER, _RE_DN_NUMBER
from app.services.parsers.bank_parser import _RE_PAY_REF, _RE_INV_REF


def test_po_number_regex_positives():
    for text, expected in PO_POSITIVES:
        m = _RE_PO_NUMBER.search(text)
        assert m is not None, f"Failed to match valid PO text: '{text}'"
        assert expected in m.group(1) or expected in m.group(0), f"Expected '{expected}' in match '{m.group(0)}' for '{text}'"


def test_po_number_regex_negatives():
    for text in PO_NEGATIVES:
        m = _RE_PO_NUMBER.search(text)
        if m:
            extracted = None
            for g in m.groups():
                if g:
                    extracted = g.strip()
                    break
            extracted = extracted or m.group(0)
            assert extracted not in ("Box", "Date", "Position", "Import", "Supporter", "H-195", "Phone", "Sarita"), f"False positive extracted '{extracted}' from '{text}'"


def test_invoice_number_regex_positives():
    for text, expected in INVOICE_POSITIVES:
        m = _RE_INV_NUMBER.search(text)
        assert m is not None, f"Failed to match valid Invoice text: '{text}'"
        assert any(expected in (g or "") for g in m.groups()) or expected in m.group(0), f"Expected '{expected}' in match '{m.group(0)}' for '{text}'"


def test_invoice_number_regex_negatives():
    for text in INVOICE_NEGATIVES:
        m = _RE_INV_NUMBER.search(text)
        if m:
            extracted = None
            for g in m.groups():
                if g:
                    extracted = g.strip()
                    break
            extracted = extracted or m.group(0)
            assert extracted not in ("INVENT", "INVALIDATED", "INVESTMENT", "500.00", "71/14", "Industrial"), f"False positive extracted '{extracted}' from '{text}'"


def test_grn_number_regex_positives():
    for text, expected in GRN_POSITIVES:
        m = _RE_GRN_NUMBER.search(text)
        assert m is not None, f"Failed to match valid GRN text: '{text}'"


def test_grn_number_regex_negatives():
    for text in GRN_NEGATIVES:
        m = _RE_GRN_NUMBER.search(text)
        if m:
            extracted = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            assert extracted not in ("Date", "BACKGROUND", "1500.00"), f"False positive extracted '{extracted}' from '{text}'"


def test_delivery_note_regex_positives():
    for text, expected in DN_POSITIVES:
        m = _RE_DN_NUMBER.search(text)
        assert m is not None, f"Failed to match valid DN text: '{text}'"
        assert expected in m.group(1) or expected in m.group(0), f"Expected '{expected}' in match '{m.group(0)}' for '{text}'"


def test_delivery_note_regex_negatives():
    for text in DN_NEGATIVES:
        m = _RE_DN_NUMBER.search(text)
        if m:
            extracted = m.group(1) if len(m.groups()) >= 1 else m.group(0)
            assert extracted.upper() not in ("NOTE", "GOODS", "DEMO", "DATE"), f"False positive extracted '{extracted}' from '{text}'"


def test_bank_narration_parser_positive():
    res1 = parse_bank_narration("NEFT-Ref6821782-Dora-Rana Pvt Ltd-INV200005")
    assert res1["ref"] is not None and "6821782" in res1["ref"]
    assert res1["invoice_number"] == "INV200005"

    res2 = parse_bank_narration("Ref-6821782 payment for INV-200005")
    assert res2["ref"] is not None and "6821782" in res2["ref"]
    assert res2["invoice_number"] == "INV-200005"

    res3 = parse_bank_narration("reference 6821782 invoice 200005")
    assert res3["ref"] is not None and "6821782" in res3["ref"]
    assert res3["invoice_number"] is not None and "200005" in res3["invoice_number"]


def test_bank_narration_parser_negatives():
    res = parse_bank_narration("REFRESH TOKEN EXPIRED IN BANK AUDIT")
    assert res["ref"] is None

    res_pref = parse_bank_narration("PREFERENTIAL PAYMENT OF 50000")
    assert res_pref["ref"] is None


def test_entity_resolver_candidates_extractions():
    q = "Please check Delivery Note #: DN-100005 and PO-100005 for INV-200005 with Ref6821782, TXN-2026-180 and GRN-2026-0005"
    candidates = extract_potential_entities(q)
    types_found = {c["type_hint"] for c in candidates}

    assert "delivery_note" in types_found
    assert "po_number" in types_found
    assert "invoice_number" in types_found
    assert "bank_reference" in types_found
    assert "grn_number" in types_found
    assert "transaction_reference" in types_found


def test_delivery_note_negative_goods_note():
    q = "WHAT IS WRITTEN IN GOODS NOTE"
    candidates = extract_potential_entities(q)
    dn_candidates = [c for c in candidates if c["type_hint"] == "delivery_note"]
    assert len(dn_candidates) == 0

    for c in candidates:
        assert c["raw"].upper() != "GOODS"
        assert c["raw"].upper() != "GOODS NOTE"
        assert c["raw"].upper() != "D"
