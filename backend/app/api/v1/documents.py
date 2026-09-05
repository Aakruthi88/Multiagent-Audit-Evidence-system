from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import (
    Document, PurchaseOrder, Invoice, GRN, BankStatement
)
from app.schemas.bundle_schemas import DocumentDetailResponse

router = APIRouter(prefix="/documents", tags=["documents"])

@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    document_id: UUID,
    db: Session = Depends(get_db)
):
    """GET /api/v1/documents/{document_id} - Fetch raw text & extracted JSON for a specific document."""
    doc = db.query(Document).filter(Document.document_id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    extracted_data = None

    if doc.doc_type == "purchase_order":
        po = db.query(PurchaseOrder).filter(PurchaseOrder.document_id == document_id).first()
        if po:
            extracted_data = {
                "po_number": po.po_number,
                "po_date": str(po.po_date) if po.po_date else None,
                "vendor_name": po.vendor.name_raw if po.vendor else None,
                "subtotal": float(po.subtotal),
                "tax_rate": float(po.tax_rate) if po.tax_rate else 0.0,
                "tax_amount": float(po.tax_amount) if po.tax_amount else 0.0,
                "total_amount": float(po.total_amount),
                "line_items": [
                    {
                        "description": item.description,
                        "qty": float(item.qty),
                        "unit_price": float(item.unit_price),
                        "line_total": float(item.line_total)
                    } for item in po.line_items
                ]
            }

    elif doc.doc_type == "invoice":
        inv = db.query(Invoice).filter(Invoice.document_id == document_id).first()
        if inv:
            extracted_data = {
                "invoice_number": inv.invoice_number,
                "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "po_ref_raw": inv.po_ref_raw,
                "vendor_name": inv.vendor.name_raw if inv.vendor else None,
                "subtotal": float(inv.subtotal),
                "tax_rate": float(inv.tax_rate) if inv.tax_rate else 0.0,
                "tax_amount": float(inv.tax_amount) if inv.tax_amount else 0.0,
                "total_amount": float(inv.total_amount),
                "line_items": [
                    {
                        "description": item.description,
                        "qty": float(item.qty) if item.qty else None,
                        "unit_price": float(item.unit_price) if item.unit_price else None,
                        "line_total": float(item.line_total) if item.line_total else None
                    } for item in inv.line_items
                ]
            }

    elif doc.doc_type == "grn":
        grn = db.query(GRN).filter(GRN.document_id == document_id).first()
        if grn:
            extracted_data = {
                "grn_number": grn.grn_number,
                "grn_date": str(grn.grn_date) if grn.grn_date else None,
                "delivery_note_number": grn.delivery_note_number,
                "po_ref_raw": grn.po_ref_raw,
                "vendor_name": grn.vendor.name_raw if grn.vendor else None,
                "total_amount": float(grn.total_amount),
                "received_condition": grn.received_condition,
                "line_items": [
                    {
                        "description": item.description,
                        "qty_ordered": float(item.qty_ordered) if item.qty_ordered else None,
                        "qty_received": float(item.qty_received) if item.qty_received else None,
                        "line_total": float(item.line_total) if item.line_total else None
                    } for item in grn.line_items
                ]
            }

    elif doc.doc_type == "bank_statement":
        bs = db.query(BankStatement).filter(BankStatement.document_id == document_id).first()
        if bs:
            extracted_data = {
                "account_number": bs.account_number,
                "statement_date": str(bs.statement_date) if bs.statement_date else None,
                "opening_balance": float(bs.opening_balance) if bs.opening_balance else 0.0,
                "closing_balance": float(bs.closing_balance) if bs.closing_balance else 0.0,
                "transactions": [
                    {
                        "txn_date": str(txn.txn_date),
                        "description_raw": txn.description_raw,
                        "debit_amount": float(txn.debit_amount) if txn.debit_amount else 0.0,
                        "credit_amount": float(txn.credit_amount) if txn.credit_amount else 0.0,
                        "extracted_ref": txn.extracted_ref,
                        "extracted_invoice_number": txn.extracted_invoice_number
                    } for txn in bs.transactions
                ]
            }

    return DocumentDetailResponse(
        document_id=doc.document_id,
        bundle_id=doc.bundle_id,
        doc_type=doc.doc_type,
        file_path=doc.file_path,
        file_hash=doc.file_hash,
        extraction_status=doc.extraction_status,
        extraction_confidence=doc.extraction_confidence,
        extraction_model=doc.extraction_model,
        uploaded_at=doc.uploaded_at,
        raw_text=doc.raw_text,
        extracted_data=extracted_data
    )
