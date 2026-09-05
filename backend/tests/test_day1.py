import fitz  # PyMuPDF
import sys
from pathlib import Path

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models  # register ORM models
from app.models.models import (
    AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement, AgentExecutionLog
)
from app.services.pdf_service import pdf_service
from app.workers.tasks import process_bundle_task

def create_sample_pdf(file_path: Path, lines: list):
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=10)
        y += 20
    doc.save(str(file_path))
    doc.close()

def run_day1_tests():
    print("=== TESTING REAL SYNTHETIC AUDIT BUNDLE FORMATS ===")
    
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    test_dir = Path("./storage/test_samples_v2")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    po_pdf = test_dir / "purchase_order.pdf"
    inv_pdf = test_dir / "invoice.pdf"
    grn_pdf = test_dir / "grn.pdf"
    bank_pdf = test_dir / "bank_statement.pdf"
    
    # Exact text layout matching user's synthetic bundle
    create_sample_pdf(po_pdf, [
        "TECHGURUPLUS SOLUTIONS PVT LTD",
        "H-195, Sarita Vihar, New Delhi 110076 PURCHASE ORDER",
        "Phone: 011-4356 7890 DATE 02-05-2026",
        "PO # 100001",
        "VENDOR Dora-Rana Pvt Ltd Priya Nair",
        "H.No. 815, Bhardwaj, Agra-661318",
        "ITEM # DESCRIPTION QTY UNIT PRICE TOTAL",
        "64810 Office Chairs - Ergonomic 13 8,500.00 110,500.00",
        "SUBTOTAL 110,500.00",
        "TAX (18%) 19,890.00",
        "TOTAL Rs. 130,390.00"
    ])

    create_sample_pdf(inv_pdf, [
        "Dora-Rana Pvt Ltd H.No. 815, Bhardwaj, Agra-661318 INVOICE",
        "DATE 08-05-2026",
        "INVOICE # 200001",
        "DUE DATE 07-06-2026",
        "PO REF 100001",
        "BILL TO Priya Nair TECHGURUPLUS SOLUTIONS PVT LTD",
        "DESCRIPTION TAXED AMOUNT",
        "Office Chairs - Ergonomic (Qty 13 x 8,500.00) X 110,500.00",
        "Subtotal 110,500.00",
        "Tax due 19,890.00",
        "TOTAL $ 130,390.00"
    ])

    create_sample_pdf(grn_pdf, [
        "GOODS RECEIVED NOTE",
        "GRN NUMBER: GRN-2026-0001 DATE: 09-05-2026",
        "Delivery Note #: DN-100001 Supplier Name: Dora-Rana Pvt Ltd",
        "PO Ref: 100001",
        "ITEM DESCRIPTION UNIT QTY ORDERED QTY RECEIVED UNIT PRICE TOTAL PRICE",
        "Item 1 Office Chairs - Ergonomic Nos 13 13 8,500.00 110,500.00",
        "TOTAL AMOUNT 110,500.00",
        "RECEIVED CONDITION: Goods received in good condition, matches PO in full."
    ])

    create_sample_pdf(bank_pdf, [
        "MERIDIAN TRUST BANK STATEMENT OF ACCOUNT",
        "Account Number: 308-246-281948",
        "Statement Date: 03/05/2026",
        "TECHGURUPLUS SOLUTIONS PVT LTD Opening Balance: 850,000.00",
        "Closing Balance: 843,344.23",
        "03/05/2026 NEFT-Ref7655194-Dora-Rana Pvt Ltd-INV200001 130,390.00 843,344.23"
    ])

    txn_ref = "TXN-2026-REAL-BUNDLE"
    existing = db.query(AuditBundle).filter(AuditBundle.txn_reference == txn_ref).first()
    if existing:
        db.delete(existing)
        db.commit()

    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle)
    db.flush()

    docs_map = {
        "purchase_order": str(po_pdf),
        "invoice": str(inv_pdf),
        "grn": str(grn_pdf),
        "bank_statement": str(bank_pdf)
    }

    doc_paths = {}
    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="dummy_hash_real",
            extraction_status="pending"
        )
        db.add(doc)
        doc_paths[dtype] = fpath

    db.commit()

    print("[Executing LangGraph Extraction Workflow...]")
    process_bundle_task(str(bundle.bundle_id), doc_paths)

    db.refresh(bundle)
    print(f"Bundle Status = '{bundle.status}'")
    
    docs = db.query(Document).filter(Document.bundle_id == bundle.bundle_id).all()
    all_passed = True
    for doc in docs:
        print(f"  -> Document '{doc.doc_type}': Status = '{doc.extraction_status}'")
        if doc.extraction_status != "success":
            all_passed = False

    po_rec = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle.bundle_id).first()
    inv_rec = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
    grn_rec = db.query(GRN).filter(GRN.bundle_id == bundle.bundle_id).first()
    bs_rec = db.query(BankStatement).filter(BankStatement.bundle_id == bundle.bundle_id).first()

    print("Extracted Records:")
    print("  -> PO #:", po_rec.po_number if po_rec else "N/A", "| PO Date:", po_rec.po_date if po_rec else "N/A", "| Total:", po_rec.total_amount if po_rec else 0)
    print("  -> Invoice #:", inv_rec.invoice_number if inv_rec else "N/A", "| PO Ref:", inv_rec.po_ref_raw if inv_rec else "N/A", "| Total:", inv_rec.total_amount if inv_rec else 0)
    print("  -> GRN #:", grn_rec.grn_number if grn_rec else "N/A", "| Total (pre-tax):", grn_rec.total_amount if grn_rec else 0)
    print("  -> Bank Acc:", bs_rec.account_number if bs_rec else "N/A")

    assert all_passed, "Some documents failed extraction!"
    print("=== ALL REAL SYNTHETIC AUDIT BUNDLE TESTS PASSED CLEANLY! ===")

if __name__ == "__main__":
    run_day1_tests()
