import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.models import (
    AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement, AgentExecutionLog
)
from app.services.extraction_service import extraction_service
from app.services.verification_service import verification_service

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db():
    session = TestSession()
    yield session
    session.close()

def test_extraction_debug_mode_and_clean_verification(db):
    """
    Tests Extraction Debug Mode snapshots in AgentExecutionLog
    and verifies 100% extraction accuracy on real synthetic bundle formats.
    """
    bundle = AuditBundle(txn_reference="TXN-DEBUG-TEST-001", status="uploaded")
    db.add(bundle)
    db.commit()
    db.refresh(bundle)

    po_text = """TECHGURUPLUS SOLUTIONS PVT LTD
H-195, Sarita Vihar, New Delhi 110076 PURCHASE ORDER
Phone: 011-4356 7890 DATE 02-05-2026
PO # 100001
VENDOR Dora-Rana Pvt Ltd Priya Nair
H.No. 815, Bhardwaj, Agra-661318
ITEM # DESCRIPTION QTY UNIT PRICE TOTAL
64810 Office Chairs - Ergonomic 13 8,500.00 110,500.00
SUBTOTAL 110,500.00
TAX (18%) 19,890.00
TOTAL Rs. 130,390.00"""

    inv_text = """Dora-Rana Pvt Ltd H.No. 815, Bhardwaj, Agra-661318 INVOICE
DATE 08-05-2026
INVOICE # 200001
DUE DATE 07-06-2026
PO REF 100001
BILL TO Priya Nair TECHGURUPLUS SOLUTIONS PVT LTD
DESCRIPTION TAXED AMOUNT
Office Chairs - Ergonomic (Qty 13 x 8,500.00) X 110,500.00
Subtotal 110,500.00
Tax due 19,890.00
TOTAL $ 130,390.00"""

    grn_text = """GOODS RECEIVED NOTE
GRN NUMBER: GRN-2026-0001 DATE: 09-05-2026
Delivery Note #: DN-100001 Supplier Name: Dora-Rana Pvt Ltd
PO Ref: 100001
ITEM DESCRIPTION UNIT QTY ORDERED QTY RECEIVED UNIT PRICE TOTAL PRICE
Item 1 Office Chairs - Ergonomic Nos 13 13 8,500.00 110,500.00
TOTAL AMOUNT 110,500.00
RECEIVED CONDITION: Goods received in good condition, matches PO in full."""

    bank_text = """MERIDIAN TRUST BANK STATEMENT OF ACCOUNT
Account Number: 308-246-281948
Statement Date: 15/05/2026
TECHGURUPLUS SOLUTIONS PVT LTD Opening Balance: 850,000.00
Closing Balance: 843,344.23
15/05/2026 NEFT-Ref7655194-Dora-Rana Pvt Ltd-INV200001 130,390.00 843,344.23"""

    docs = {
        "purchase_order": po_text,
        "invoice": inv_text,
        "grn": grn_text,
        "bank_statement": bank_text
    }

    for dtype, text in docs.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=f"/dummy/{dtype}.pdf",
            file_hash="dummyhash",
            raw_text=text,
            extraction_status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        success, data = extraction_service.extract_document(db, doc)
        assert success, f"Extraction failed for {dtype}"

        # Verify debug logging mode in AgentExecutionLog
        log = db.query(AgentExecutionLog).filter_by(
            bundle_id=bundle.bundle_id,
            agent_name=f"document_understanding_{dtype}"
        ).first()
        assert log is not None, f"Debug log missing for {dtype}"
        assert "raw_text" in log.input_snapshot
        assert "prompt" in log.input_snapshot
        assert "extracted_data" in log.output_snapshot
        assert log.status == "success"

    # Verify structured record details
    po = db.query(PurchaseOrder).filter_by(bundle_id=bundle.bundle_id).first()
    inv = db.query(Invoice).filter_by(bundle_id=bundle.bundle_id).first()
    grn = db.query(GRN).filter_by(bundle_id=bundle.bundle_id).first()
    bs = db.query(BankStatement).filter_by(bundle_id=bundle.bundle_id).first()

    assert po.po_number == "100001"
    assert float(po.total_amount) == 130390.00
    assert po.vendor.name_raw.strip() == "Dora-Rana Pvt Ltd"

    assert inv.invoice_number == "200001"
    assert float(inv.total_amount) == 130390.00
    assert inv.vendor.name_raw.strip() == "Dora-Rana Pvt Ltd"

    assert grn.grn_number == "GRN-2026-0001"
    assert float(grn.total_amount) == 110500.00  # Pre-tax total

    assert bs.account_number == "308-246-281948"

    # Run deterministic Verification Agent checks
    run = verification_service.run_all_checks(db, bundle)

    from app.models.models import VerificationCheck, Discrepancy
    checks = db.query(VerificationCheck).filter_by(run_id=run.run_id).all()
    discs = db.query(Discrepancy).filter_by(run_id=run.run_id).all()
    print("\n--- VERIFICATION CHECKS ---")
    for c in checks:
        print(f"Check: {c.check_type} | Status: {c.status} | Expected: {c.expected_value} | Actual: {c.actual_value} | Severity: {c.severity}")
    print("--- DISCREPANCIES ---")
    for d in discs:
        print(f"Disc: {d.category} | Severity: {d.severity} | Desc: {d.description}")

    assert run.overall_status == "clean", f"Verification expected clean but got '{run.overall_status}'"
    assert float(run.overall_risk_score) == 0.0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
