"""
extraction_service.py
---------------------
Thin strategy router that dispatches document extraction requests to dedicated
parsers in the `app.services.parsers` package.

Maintains DB persistence logic and agent execution logging.
"""

import time
import re
from datetime import datetime, date
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.models import (
    Document, PurchaseOrder, POLineItem, Invoice, InvoiceLineItem,
    GRN, GRNLineItem, BankStatement, BankTransaction, Vendor, AgentExecutionLog
)
from app.services.matching_utils import normalize_vendor_name, parse_bank_narration
from app.services.parsers import (
    PurchaseOrderParser,
    InvoiceParser,
    GRNParser,
    BankStatementParser
)
from app.services.parsers.text_utils import extract_pdf_text, parse_date_flexible, normalize_date


def format_date_iso(date_str: Optional[str]) -> str:
    """Returns ISO format date string YYYY-MM-DD or default today."""
    norm = normalize_date(date_str)
    if norm:
        return norm
    return datetime.utcnow().strftime("%Y-%m-%d")


class ExtractionService:
    """
    Router service that maps document types to their strategy parser implementation.
    """

    def __init__(self):
        self.parsers = {
            "purchase_order": PurchaseOrderParser(),
            "invoice": InvoiceParser(),
            "grn": GRNParser(),
            "bank_statement": BankStatementParser(),
        }

    def extract_document(self, db: Session, document: Document) -> Tuple[bool, Dict[str, Any]]:
        """
        Extracts structured data from a document using strategy pattern parsers.
        Stores output into PostgreSQL DB tables and logs execution details.
        """
        doc_type = document.doc_type
        logger.info(f"Starting extraction for document {document.document_id} ({doc_type})")

        parser = self.parsers.get(doc_type)
        if not parser:
            raise ValueError(f"Unsupported doc_type: {doc_type}")

        # Ensure raw text is extracted if missing
        raw_text = document.raw_text or ""
        if not raw_text or len(raw_text.strip()) < 10:
            try:
                raw_text = extract_pdf_text(document.file_path)
                document.raw_text = raw_text
                db.commit()
            except Exception as e:
                logger.warning(f"Could not extract raw text from {document.file_path}: {e}")

        # Dispatch to strategy parser
        result = parser.timed_extract(pdf_path=document.file_path, raw_text=raw_text)
        return self.persist_extraction_result(db, document, result)

    def persist_extraction_result(self, db: Session, document: Document, result: Any) -> Tuple[bool, Dict[str, Any]]:
        """
        Persists an ExtractionResult to the database and logs execution details.
        Safe to call from the main persistence loop following concurrent parsing.
        """
        doc_type = document.doc_type

        # Handle persistence if parsing was successful
        if result.success and result.extracted_obj:
            try:
                self._save_to_db(db, document, doc_type, result.extracted_obj)
                
                # Determine status based on rubric confidence
                status_str = "success" if result.confidence >= 0.60 else "low_confidence"
                document.extraction_status = status_str
                document.extraction_confidence = result.confidence
                document.extraction_model = result.model_used
                db.commit()

                # Log execution in AgentExecutionLog
                log_entry = AgentExecutionLog(
                    bundle_id=document.bundle_id,
                    agent_name=f"document_understanding_{doc_type}",
                    input_snapshot={
                        "document_id": str(document.document_id),
                        "doc_type": doc_type,
                        "raw_text": result.raw_text,
                        "cleaned_text": result.cleaned_text,
                        "prompt": result.prompt,
                    },
                    output_snapshot=result.to_log_snapshot(),
                    model_used=result.model_used,
                    tokens_used=result.tokens_used,
                    latency_ms=result.latency_ms,
                    status="success"
                )
                db.add(log_entry)
                db.commit()

                logger.info(
                    f"Extraction succeeded for document {document.document_id} ({doc_type}) "
                    f"via {result.model_used} in {result.latency_ms}ms with confidence {result.confidence:.2f}"
                )
                return True, result.extracted_obj.model_dump()

            except Exception as e:
                db.rollback()
                logger.error(f"Error persisting extracted data for document {document.document_id}: {e}", exc_info=True)
                document.extraction_status = "failed"
                document.extraction_confidence = result.confidence
                document.extraction_model = result.model_used
                db.commit()

                log_entry = AgentExecutionLog(
                    bundle_id=document.bundle_id,
                    agent_name=f"document_understanding_{doc_type}",
                    input_snapshot={
                        "document_id": str(document.document_id),
                        "doc_type": doc_type,
                        "raw_text": result.raw_text,
                        "cleaned_text": result.cleaned_text,
                        "prompt": result.prompt,
                    },
                    output_snapshot=result.to_log_snapshot(),
                    model_used=result.model_used,
                    tokens_used=result.tokens_used,
                    latency_ms=result.latency_ms,
                    status="error",
                    error_message=str(e)
                )
                db.add(log_entry)
                db.commit()

                return False, {"error": str(e)}

        # Extraction failed
        document.extraction_status = "failed"
        document.extraction_confidence = result.confidence if result else 0.0
        document.extraction_model = result.model_used if result else "unknown"
        db.commit()

        log_entry = AgentExecutionLog(
            bundle_id=document.bundle_id,
            agent_name=f"document_understanding_{doc_type}",
            input_snapshot={
                "document_id": str(document.document_id),
                "doc_type": doc_type,
                "raw_text": result.raw_text if result else None,
                "cleaned_text": result.cleaned_text if result else None,
                "prompt": result.prompt if result else None,
            },
            output_snapshot=result.to_log_snapshot() if result else {},
            model_used=result.model_used if result else "unknown",
            tokens_used=result.tokens_used if result else 0,
            latency_ms=result.latency_ms if result else 0,
            status="failed",
            error_message="; ".join(result.validation_errors) if (result and result.validation_errors) else "Extraction failed"
        )
        db.add(log_entry)
        db.commit()

        logger.warning(
            f"Extraction failed for document {document.document_id} ({doc_type}): "
            f"{result.validation_errors if result else 'No result'}"
        )
        return False, {"error": (result.validation_errors if result else None) or ["Extraction failed"]}

    def _save_to_db(self, db: Session, document: Document, doc_type: str, extracted: Any):
        """Maps Pydantic extraction object directly to SQLAlchemy ORM models using flexible date parsing."""
        bundle_id = document.bundle_id

        if doc_type == "purchase_order":
            existing_po = db.query(PurchaseOrder).filter(PurchaseOrder.document_id == document.document_id).first()
            if existing_po:
                db.delete(existing_po)
                db.flush()

            vendor = self._get_or_create_vendor(db, extracted.vendor_name)
            po = PurchaseOrder(
                document_id=document.document_id,
                bundle_id=bundle_id,
                po_number=extracted.po_number,
                po_date=parse_date_flexible(extracted.po_date),
                vendor_id=vendor.vendor_id,
                requisitioner=extracted.requisitioner,
                shipping_terms=extracted.shipping_terms,
                subtotal=extracted.subtotal,
                tax_rate=extracted.tax_rate,
                tax_amount=extracted.tax_amount,
                total_amount=extracted.total_amount
            )
            db.add(po)
            db.flush()

            for item in extracted.line_items:
                line = POLineItem(
                    po_id=po.po_id,
                    item_code=item.item_code,
                    description=item.description,
                    qty=item.qty,
                    unit_price=item.unit_price,
                    line_total=item.line_total
                )
                db.add(line)

        elif doc_type == "invoice":
            existing_inv = db.query(Invoice).filter(Invoice.document_id == document.document_id).first()
            if existing_inv:
                db.delete(existing_inv)
                db.flush()

            vendor = self._get_or_create_vendor(db, extracted.vendor_name)
            po_match = None
            if extracted.po_ref_raw:
                po_match = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == extracted.po_ref_raw).first()

            inv = Invoice(
                document_id=document.document_id,
                bundle_id=bundle_id,
                invoice_number=extracted.invoice_number,
                invoice_date=parse_date_flexible(extracted.invoice_date),
                due_date=parse_date_flexible(extracted.due_date),
                po_ref_raw=extracted.po_ref_raw,
                po_id=po_match.po_id if po_match else None,
                vendor_id=vendor.vendor_id,
                subtotal=extracted.subtotal,
                tax_rate=extracted.tax_rate,
                tax_amount=extracted.tax_amount,
                total_amount=extracted.total_amount
            )
            db.add(inv)
            db.flush()

            for item in extracted.line_items:
                line = InvoiceLineItem(
                    invoice_id=inv.invoice_id,
                    description=item.description,
                    qty=item.qty,
                    unit_price=item.unit_price,
                    line_total=item.line_total
                )
                db.add(line)

        elif doc_type == "grn":
            existing_grn = db.query(GRN).filter(GRN.document_id == document.document_id).first()
            if existing_grn:
                db.delete(existing_grn)
                db.flush()

            vendor = self._get_or_create_vendor(db, extracted.vendor_name or "Dora-Rana Pvt Ltd")
            po_match = None
            if extracted.po_ref_raw:
                po_match = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == extracted.po_ref_raw).first()

            grn = GRN(
                document_id=document.document_id,
                bundle_id=bundle_id,
                grn_number=extracted.grn_number,
                grn_date=parse_date_flexible(extracted.grn_date),
                delivery_note_number=extracted.delivery_note_number,
                po_ref_raw=extracted.po_ref_raw,
                po_id=po_match.po_id if po_match else None,
                vendor_id=vendor.vendor_id,
                total_amount=extracted.total_amount,
                received_condition=extracted.received_condition
            )
            db.add(grn)
            db.flush()

            for item in extracted.line_items:
                line = GRNLineItem(
                    grn_id=grn.grn_id,
                    description=item.description,
                    qty_ordered=item.qty_ordered,
                    qty_received=item.qty_received,
                    unit_price=item.unit_price,
                    line_total=item.line_total
                )
                db.add(line)

        elif doc_type == "bank_statement":
            existing_bs = db.query(BankStatement).filter(BankStatement.document_id == document.document_id).first()
            if existing_bs:
                db.delete(existing_bs)
                db.flush()

            bs = BankStatement(
                document_id=document.document_id,
                bundle_id=bundle_id,
                account_number=extracted.account_number,
                statement_date=parse_date_flexible(extracted.statement_date),
                period_start=parse_date_flexible(extracted.period_start),
                period_end=parse_date_flexible(extracted.period_end),
                opening_balance=extracted.opening_balance,
                closing_balance=extracted.closing_balance
            )
            db.add(bs)
            db.flush()

            for txn in extracted.transactions:
                pay_ref = getattr(txn, 'payment_reference', None)
                inv_ref = getattr(txn, 'invoice_reference', None)
                vendor_frag = getattr(txn, 'vendor_name', None)

                if not any([pay_ref, inv_ref, vendor_frag]):
                    narr_parsed = parse_bank_narration(txn.description_raw)
                    pay_ref = narr_parsed.get("ref")
                    inv_ref = narr_parsed.get("invoice_number")
                    vendor_frag = narr_parsed.get("vendor_fragment")

                bt = BankTransaction(
                    statement_id=bs.statement_id,
                    txn_date=parse_date_flexible(txn.txn_date) or datetime.utcnow().date(),
                    description_raw=txn.description_raw,
                    credit_amount=txn.credit_amount,
                    debit_amount=txn.debit_amount,
                    running_balance=txn.running_balance,
                    extracted_ref=pay_ref,
                    extracted_vendor_fragment=vendor_frag,
                    extracted_invoice_number=inv_ref
                )
                db.add(bt)

    def _get_or_create_vendor(self, db: Session, name_raw: str) -> Vendor:
        norm = normalize_vendor_name(name_raw)
        vendor = db.query(Vendor).filter(Vendor.name_normalized == norm).first()
        if not vendor:
            vendor = Vendor(
                name_raw=name_raw,
                name_normalized=norm or name_raw.lower()
            )
            db.add(vendor)
            db.flush()
        return vendor


extraction_service = ExtractionService()
