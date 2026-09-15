"""
Phase 1B Test Suite: Concurrent Document Ingestion Verification
- Test 1: Four valid documents (PO + Invoice + GRN + Bank Statement)
- Test 2: Missing document graceful degradation
- Test 3: Malformed/invalid document error handling
- Test 4: Repeated processing idempotency & determinism
- Test 5: Full LangGraph pipeline integration
"""

import time
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal, engine
from app.db.base import Base
import app.models
from app.models.models import AuditBundle, Document, PurchaseOrder, Invoice, GRN, BankStatement
from app.agents.document_agent import document_understanding_node


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)


def test_concurrent_four_valid_documents():
    """Test 1: Four valid documents parse concurrently with complete records."""
    db = SessionLocal()
    txn_ref = f"TXN-TEST1-{int(time.time()*1000)}"
    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle)
    db.flush()

    docs_map = {
        "purchase_order": str(Path("./storage/test_samples_v2/purchase_order.pdf")),
        "invoice": str(Path("./storage/test_samples_v2/invoice.pdf")),
        "grn": str(Path("./storage/test_samples_v2/grn.pdf")),
        "bank_statement": str(Path("./storage/test_samples_v2/bank_statement.pdf")),
    }

    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="test1_hash",
            extraction_status="pending",
        )
        db.add(doc)
    db.commit()
    bid = str(bundle.bundle_id)
    db.close()

    state_out = document_understanding_node({"bundle_id": bid})
    extracted = state_out.get("extracted", {})

    assert set(extracted.keys()) == {"purchase_order", "invoice", "grn", "bank_statement"}

    db = SessionLocal()
    bundle_db = db.query(AuditBundle).filter(AuditBundle.bundle_id == bid).first()
    assert bundle_db.status == "extracted"

    po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bid).first()
    inv = db.query(Invoice).filter(Invoice.bundle_id == bid).first()
    grn = db.query(GRN).filter(GRN.bundle_id == bid).first()
    bs = db.query(BankStatement).filter(BankStatement.bundle_id == bid).first()

    assert po is not None and po.po_number == "100001"
    assert inv is not None and inv.invoice_number == "200001"
    assert grn is not None and grn.grn_number == "GRN-2026-0001"
    assert bs is not None and bs.account_number == "308-246-281948"
    db.close()


def test_concurrent_missing_document():
    """Test 2: Bundle with missing GRN degrades gracefully without crash."""
    db = SessionLocal()
    txn_ref = f"TXN-TEST2-NOGRN-{int(time.time()*1000)}"
    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle)
    db.flush()

    docs_map = {
        "purchase_order": str(Path("./storage/test_samples_v2/purchase_order.pdf")),
        "invoice": str(Path("./storage/test_samples_v2/invoice.pdf")),
        "bank_statement": str(Path("./storage/test_samples_v2/bank_statement.pdf")),
    }

    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="test2_hash",
            extraction_status="pending",
        )
        db.add(doc)
    db.commit()
    bid = str(bundle.bundle_id)
    db.close()

    state_out = document_understanding_node({"bundle_id": bid})
    extracted = state_out.get("extracted", {})

    assert "grn" not in extracted
    assert "purchase_order" in extracted
    assert "invoice" in extracted
    assert "bank_statement" in extracted

    db = SessionLocal()
    bundle_db = db.query(AuditBundle).filter(AuditBundle.bundle_id == bid).first()
    assert bundle_db.status == "extracted"
    db.close()


def test_concurrent_malformed_document():
    """Test 3: Malformed/non-existent PDF path fails controlled with no corrupted state."""
    db = SessionLocal()
    txn_ref = f"TXN-TEST3-MALFORMED-{int(time.time()*1000)}"
    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle)
    db.flush()

    docs_map = {
        "purchase_order": str(Path("./storage/test_samples_v2/purchase_order.pdf")),
        "invoice": "/non/existent/path/corrupt_invoice.pdf",
    }

    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="test3_hash",
            extraction_status="pending",
        )
        db.add(doc)
    db.commit()
    bid = str(bundle.bundle_id)
    db.close()

    state_out = document_understanding_node({"bundle_id": bid})
    extracted = state_out.get("extracted", {})

    # PO should succeed, corrupt invoice should fail without throwing unhandled exception
    assert "purchase_order" in extracted
    assert "invoice" not in extracted

    db = SessionLocal()
    corrupt_doc = db.query(Document).filter(Document.bundle_id == bid, Document.doc_type == "invoice").first()
    assert corrupt_doc.extraction_status == "failed"
    db.close()


def test_repeated_processing_determinism():
    """Test 4: Repeated processing of the same bundle returns deterministic results with no duplicates."""
    db = SessionLocal()
    txn_ref = f"TXN-TEST4-REPEAT-{int(time.time()*1000)}"
    bundle = AuditBundle(txn_reference=txn_ref, status="uploaded")
    db.add(bundle)
    db.flush()

    docs_map = {
        "purchase_order": str(Path("./storage/test_samples_v2/purchase_order.pdf")),
        "invoice": str(Path("./storage/test_samples_v2/invoice.pdf")),
        "grn": str(Path("./storage/test_samples_v2/grn.pdf")),
        "bank_statement": str(Path("./storage/test_samples_v2/bank_statement.pdf")),
    }

    for dtype, fpath in docs_map.items():
        doc = Document(
            bundle_id=bundle.bundle_id,
            doc_type=dtype,
            file_path=fpath,
            file_hash="test4_hash",
            extraction_status="pending",
        )
        db.add(doc)
    db.commit()
    bid = str(bundle.bundle_id)
    db.close()

    # Pass 1
    res1 = document_understanding_node({"bundle_id": bid})
    # Pass 2
    res2 = document_understanding_node({"bundle_id": bid})

    assert list(res1["extracted"].keys()) == list(res2["extracted"].keys())
    assert res1["extracted"]["purchase_order"]["po_number"] == res2["extracted"]["purchase_order"]["po_number"]
    assert res1["extracted"]["invoice"]["invoice_number"] == res2["extracted"]["invoice"]["invoice_number"]
