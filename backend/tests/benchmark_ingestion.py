import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models
from app.models.models import AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement
from app.agents.document_agent import document_understanding_node

def run_benchmark(label="ingestion_benchmark"):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    txn_ref = f"TXN-BENCHMARK-{int(time.time()*1000)}"
    b = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(b)
    db.flush()
    
    docs_map = {
        "purchase_order": str(Path("./storage/test_samples_v2/purchase_order.pdf")),
        "invoice": str(Path("./storage/test_samples_v2/invoice.pdf")),
        "grn": str(Path("./storage/test_samples_v2/grn.pdf")),
        "bank_statement": str(Path("./storage/test_samples_v2/bank_statement.pdf"))
    }
    
    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=b.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="bench_hash",
            extraction_status="pending"
        )
        db.add(doc)
    db.commit()
    bundle_id = str(b.bundle_id)
    db.close()
    
    start = time.time()
    state_out = document_understanding_node({"bundle_id": bundle_id})
    elapsed_ms = (time.time() - start) * 1000
    
    extracted = state_out.get("extracted", {})
    print(f"[{label}] Elapsed: {elapsed_ms:.2f} ms")
    print(f"[{label}] Extracted doc types: {list(extracted.keys())}")
    
    db = SessionLocal()
    po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle_id).first()
    inv = db.query(Invoice).filter(Invoice.bundle_id == bundle_id).first()
    grn = db.query(GRN).filter(GRN.bundle_id == bundle_id).first()
    bs = db.query(BankStatement).filter(BankStatement.bundle_id == bundle_id).first()
    
    assert po is not None and po.po_number == "100001", "PO record missing or mismatch"
    assert inv is not None and inv.invoice_number == "200001", "Invoice record missing or mismatch"
    assert grn is not None and grn.grn_number == "GRN-2026-0001", "GRN record missing or mismatch"
    assert bs is not None and bs.account_number == "308-246-281948", "Bank record missing or mismatch"
    db.close()
    
    return elapsed_ms

if __name__ == "__main__":
    ms = run_benchmark("SEQUENTIAL_BASELINE")
    print(f"FINAL_BENCHMARK_RESULT: {ms:.2f} ms")
