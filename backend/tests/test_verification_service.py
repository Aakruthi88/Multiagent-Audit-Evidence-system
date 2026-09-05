"""
tests/test_verification_service.py
Tests the deterministic VerificationService rules without calling any LLM.
All test scenarios use in-memory SQLite.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from decimal import Decimal
from datetime import date
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.models import (
    AuditBundle, Document, Vendor,
    PurchaseOrder, POLineItem,
    Invoice, InvoiceLineItem,
    GRN, GRNLineItem,
    BankStatement, BankTransaction
)
from app.services.verification_service import verification_service

# ── SQLite in-memory DB setup ─────────────────────────────────────────────────
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db():
    session = TestSession()
    yield session
    session.close()


# ── Factory helpers ───────────────────────────────────────────────────────────

def make_bundle(db, txn_ref="TXN-TEST-001") -> AuditBundle:
    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle); db.commit(); db.refresh(bundle)
    return bundle

def make_vendor(db, name="Acme Corp") -> Vendor:
    vendor = Vendor(name_raw=name, name_normalized=name.lower())
    db.add(vendor); db.commit(); db.refresh(vendor)
    return vendor

def make_po(db, bundle, vendor, po_num="PO-001", subtotal=10000, tax_rate=18, total=11800) -> PurchaseOrder:
    doc = Document(bundle_id=bundle.bundle_id, doc_type="purchase_order",
                   file_path="/tmp/po.pdf", file_hash="abc", extraction_status="success")
    db.add(doc); db.commit(); db.refresh(doc)
    po = PurchaseOrder(
        document_id=doc.document_id, bundle_id=bundle.bundle_id,
        po_number=po_num, po_date=date(2025, 1, 1), vendor_id=vendor.vendor_id,
        subtotal=subtotal, tax_rate=tax_rate, tax_amount=(subtotal*tax_rate/100),
        total_amount=total
    )
    db.add(po); db.commit(); db.refresh(po)
    return po

def make_po_line(db, po, desc="Widget A", qty=10, unit_price=1000, line_total=10000) -> POLineItem:
    line = POLineItem(po_id=po.po_id, description=desc, qty=qty,
                      unit_price=unit_price, line_total=line_total)
    db.add(line); db.commit()
    return line

def make_invoice(db, bundle, vendor, inv_num="INV-001", po_ref="PO-001",
                 subtotal=10000, tax_rate=18, tax_amount=1800, total=11800,
                 inv_date=date(2025, 1, 10)) -> Invoice:
    doc = Document(bundle_id=bundle.bundle_id, doc_type="invoice",
                   file_path="/tmp/inv.pdf", file_hash="def", extraction_status="success")
    db.add(doc); db.commit(); db.refresh(doc)
    inv = Invoice(
        document_id=doc.document_id, bundle_id=bundle.bundle_id,
        invoice_number=inv_num, invoice_date=inv_date, po_ref_raw=po_ref,
        vendor_id=vendor.vendor_id, subtotal=subtotal,
        tax_rate=tax_rate, tax_amount=tax_amount, total_amount=total
    )
    db.add(inv); db.commit(); db.refresh(inv)
    return inv

def make_inv_line(db, inv, desc="Widget A", qty=10, unit_price=1000, line_total=10000) -> InvoiceLineItem:
    line = InvoiceLineItem(invoice_id=inv.invoice_id, description=desc, qty=qty,
                           unit_price=unit_price, line_total=line_total)
    db.add(line); db.commit()
    return line

def make_grn(db, bundle, vendor, grn_num="GRN-001", po_ref="PO-001",
             total=10000, grn_date=date(2025, 1, 8)) -> GRN:
    doc = Document(bundle_id=bundle.bundle_id, doc_type="grn",
                   file_path="/tmp/grn.pdf", file_hash="ghi", extraction_status="success")
    db.add(doc); db.commit(); db.refresh(doc)
    grn = GRN(
        document_id=doc.document_id, bundle_id=bundle.bundle_id,
        grn_number=grn_num, grn_date=grn_date, po_ref_raw=po_ref,
        vendor_id=vendor.vendor_id, total_amount=total
    )
    db.add(grn); db.commit(); db.refresh(grn)
    return grn

def make_grn_line(db, grn, desc="Widget A", qty_ordered=10, qty_received=10,
                  unit_price=1000, line_total=10000) -> GRNLineItem:
    line = GRNLineItem(grn_id=grn.grn_id, description=desc, qty_ordered=qty_ordered,
                       qty_received=qty_received, unit_price=unit_price, line_total=line_total)
    db.add(line); db.commit()
    return line

def make_bank(db, bundle, acct="ACC-001") -> BankStatement:
    doc = Document(bundle_id=bundle.bundle_id, doc_type="bank_statement",
                   file_path="/tmp/bank.pdf", file_hash="jkl", extraction_status="success")
    db.add(doc); db.commit(); db.refresh(doc)
    bs = BankStatement(
        document_id=doc.document_id, bundle_id=bundle.bundle_id,
        account_number=acct, statement_date=date(2025, 1, 31)
    )
    db.add(bs); db.commit(); db.refresh(bs)
    return bs

def make_bank_txn(db, bs, txn_date, debit, inv_num, desc="Payment INV-001") -> BankTransaction:
    txn = BankTransaction(
        statement_id=bs.statement_id, txn_date=txn_date,
        description_raw=desc, debit_amount=debit,
        extracted_invoice_number=inv_num
    )
    db.add(txn); db.commit()
    return txn


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestScenario1_CleanBundle:
    """All 4 documents present and consistent — should pass as 'clean'."""

    def test_clean_bundle(self, db):
        bundle = make_bundle(db, "TXN-CLEAN-001")
        vendor = make_vendor(db, "Acme Corp")
        po = make_po(db, bundle, vendor)
        make_po_line(db, po)
        inv = make_invoice(db, bundle, vendor)
        make_inv_line(db, inv)
        grn = make_grn(db, bundle, vendor)
        make_grn_line(db, grn)
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 11800, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        assert run.overall_status == "clean", f"Expected clean, got {run.overall_status}"
        assert float(run.overall_risk_score) == 0.0
        print(f"  ✅ Scenario 1 PASS — {run.overall_status}, risk={run.overall_risk_score}")


class TestScenario2_POInvoiceMismatch:
    """Invoice total exceeds PO total — critical discrepancy."""

    def test_overbilled_invoice(self, db):
        bundle = make_bundle(db, "TXN-OVERBILL-001")
        vendor = make_vendor(db, "Beta Suppliers")
        po = make_po(db, bundle, vendor, subtotal=10000, tax_rate=18, total=11800)
        inv = make_invoice(db, bundle, vendor, subtotal=12000, tax_amount=2160, total=14160)
        grn = make_grn(db, bundle, vendor)
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 14160, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import Discrepancy, VerificationCheck
        disc = db.query(Discrepancy).filter_by(run_id=run.run_id).all()
        critical = [d for d in disc if d.severity == "critical"]

        assert run.overall_status in ("critical", "flagged")
        assert len(critical) >= 1
        assert any("overbill" in d.description.lower() or "exceeds" in d.description.lower() for d in critical)
        print(f"  ✅ Scenario 2 PASS — {run.overall_status}, criticals={len(critical)}")


class TestScenario3_GRNTaxTrap:
    """
    GRN total should match PO SUBTOTAL not PO total_amount.
    Classic audit failure — comparing GRN to post-tax PO total.
    """

    def test_grn_subtotal_comparison(self, db):
        bundle = make_bundle(db, "TXN-GRN-TAX-001")
        vendor = make_vendor(db, "Gamma Ltd")
        po = make_po(db, bundle, vendor, subtotal=50000, tax_rate=18, total=59000)
        inv = make_invoice(db, bundle, vendor, subtotal=50000, tax_amount=9000, total=59000)
        # GRN total=50000 (pre-tax) — this is correct
        grn = make_grn(db, bundle, vendor, total=50000)
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 59000, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import VerificationCheck
        grn_check = db.query(VerificationCheck).filter_by(
            run_id=run.run_id, check_type="po_grn_amount_match"
        ).first()

        # GRN 50000 should match PO SUBTOTAL 50000 → PASS (not fail)
        assert grn_check.status == "pass", (
            f"GRN vs PO SUBTOTAL check should PASS but got: {grn_check.status}. "
            f"Expected=50000, Actual={grn_check.actual_value}"
        )
        print(f"  ✅ Scenario 3 PASS — GRN correctly compared to PO subtotal, not total")


class TestScenario4_PaymentBeforeInvoice:
    """Payment date precedes invoice date — fraud indicator."""

    def test_payment_before_invoice(self, db):
        bundle = make_bundle(db, "TXN-BACKDATE-001")
        vendor = make_vendor(db, "Delta Corp")
        po = make_po(db, bundle, vendor)
        inv = make_invoice(db, bundle, vendor, inv_date=date(2025, 1, 15))
        grn = make_grn(db, bundle, vendor, grn_date=date(2025, 1, 10))
        bs = make_bank(db, bundle)
        # Payment 5 days BEFORE invoice date — fraud flag
        make_bank_txn(db, bs, date(2025, 1, 10), 11800, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import VerificationCheck
        date_check = db.query(VerificationCheck).filter_by(
            run_id=run.run_id, check_type="payment_before_invoice_date"
        ).first()

        assert date_check is not None
        assert date_check.status == "fail"
        print(f"  ✅ Scenario 4 PASS — Payment before invoice detected as {date_check.status}")


class TestScenario5_MissingDocument:
    """Missing GRN — should show incomplete status."""

    def test_missing_grn(self, db):
        bundle = make_bundle(db, "TXN-MISSING-GRN")
        vendor = make_vendor(db, "Epsilon Ltd")
        po = make_po(db, bundle, vendor)
        inv = make_invoice(db, bundle, vendor)
        # No GRN added
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 11800, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import Discrepancy
        missing_disc = db.query(Discrepancy).filter_by(
            run_id=run.run_id, category="missing_document"
        ).all()

        assert run.overall_status == "incomplete"
        assert len(missing_disc) >= 1
        assert any("grn" in d.description.lower() for d in missing_disc)
        print(f"  ✅ Scenario 5 PASS — Missing GRN detected, status={run.overall_status}")


class TestScenario6_ShortShipment:
    """GRN shows fewer items received than ordered."""

    def test_short_shipment(self, db):
        bundle = make_bundle(db, "TXN-SHORT-001")
        vendor = make_vendor(db, "Zeta Supply")
        po = make_po(db, bundle, vendor)
        make_po_line(db, po, qty=100, unit_price=100, line_total=10000)
        inv = make_invoice(db, bundle, vendor)
        grn = make_grn(db, bundle, vendor)
        # Only 80 units received out of 100 ordered
        make_grn_line(db, grn, qty_ordered=100, qty_received=80, unit_price=100, line_total=8000)
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 11800, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import Discrepancy
        disc = db.query(Discrepancy).filter_by(run_id=run.run_id, category="qty_mismatch").all()

        assert len(disc) >= 1
        assert any("short" in d.description.lower() for d in disc)
        print(f"  ✅ Scenario 6 PASS — Short shipment detected: {disc[0].description[:60]}")


class TestScenario7_VendorMismatch:
    """Vendor name on invoice differs significantly from PO vendor."""

    def test_vendor_mismatch(self, db):
        bundle = make_bundle(db, "TXN-VENDOR-001")
        po_vendor = make_vendor(db, "Acme Corporation Pvt Ltd")
        inv_vendor = make_vendor(db, "Totally Different Company")
        po = make_po(db, bundle, po_vendor)
        inv = make_invoice(db, bundle, inv_vendor)
        grn = make_grn(db, bundle, po_vendor)
        bs = make_bank(db, bundle)
        make_bank_txn(db, bs, date(2025, 1, 15), 11800, "INV-001")

        run = verification_service.run_all_checks(db, bundle)

        from app.models.models import Discrepancy
        disc = db.query(Discrepancy).filter_by(run_id=run.run_id, category="vendor_mismatch").all()

        assert len(disc) >= 1
        print(f"  ✅ Scenario 7 PASS — Vendor mismatch detected: score shown in check")


# ── Run directly ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
