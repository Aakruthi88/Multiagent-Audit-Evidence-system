import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app.agents.state import BundleState
from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import AuditBundle, Document
from app.services.extraction_service import extraction_service
from app.services.parsers.text_utils import extract_pdf_text

CANONICAL_DOC_ORDER = ["purchase_order", "invoice", "grn", "bank_statement"]


def _parse_single_doc_worker(doc_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Worker function executed concurrently in ThreadPoolExecutor.
    Performs PDF text extraction and parser execution concurrently.
    Pure parsing logic — does NOT share or mutate any database sessions.
    """
    doc_id = doc_info["document_id"]
    doc_type = doc_info["doc_type"]
    file_path = doc_info["file_path"]
    raw_text = doc_info.get("raw_text") or ""

    logger.info(f"[Document Understanding Agent] [Thread] Parsing {doc_type} for document {doc_id}")

    # Step 1: Extract PDF text if missing
    if not raw_text or len(raw_text.strip()) < 10:
        try:
            raw_text = extract_pdf_text(file_path)
        except Exception as e:
            logger.error(f"[Document Understanding Agent] Failed PDF text extraction for {doc_id} ({doc_type}): {e}")
            return {
                "document_id": doc_id,
                "doc_type": doc_type,
                "raw_text": None,
                "result": None,
                "error": f"Failed PDF text extraction: {e}",
            }

    # Step 2: Run strategy parser
    parser = extraction_service.parsers.get(doc_type)
    if not parser:
        logger.error(f"[Document Understanding Agent] No parser found for {doc_type}")
        return {
            "document_id": doc_id,
            "doc_type": doc_type,
            "raw_text": raw_text,
            "result": None,
            "error": f"Unsupported doc_type: {doc_type}",
        }

    try:
        result = parser.timed_extract(pdf_path=file_path, raw_text=raw_text)
        return {
            "document_id": doc_id,
            "doc_type": doc_type,
            "raw_text": raw_text,
            "result": result,
            "error": None,
        }
    except Exception as e:
        logger.error(f"[Document Understanding Agent] Exception in parser for {doc_id} ({doc_type}): {e}")
        return {
            "document_id": doc_id,
            "doc_type": doc_type,
            "raw_text": raw_text,
            "result": None,
            "error": str(e),
        }


def document_understanding_node(state: BundleState) -> BundleState:
    """
    Document Understanding Agent node:
    - Concurrently extracts raw text and executes strategy parsers for each document in the bundle.
    - Sequentially persists structured records and logs to DB in deterministic canonical order.
    """
    start_time = time.time()
    bundle_id = state.get("bundle_id")
    db = SessionLocal()
    extracted_results = state.get("extracted", {})

    try:
        documents = db.query(Document).filter(Document.bundle_id == bundle_id).all()
        if not documents:
            logger.warning(f"[Document Understanding Agent] No documents found for bundle {bundle_id}")
            return {**state, "extracted": extracted_results}

        # Surface "extracting" status immediately so UI updates
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        if bundle and bundle.status == "uploaded":
            bundle.status = "extracting"
            db.commit()
            logger.info(f"[Document Understanding Agent] Bundle {bundle_id} status -> extracting")

        # Prepare read-only payloads for worker threads (no DB sessions shared across threads)
        docs_payload = [
            {
                "document_id": doc.document_id,
                "doc_type": doc.doc_type,
                "file_path": doc.file_path,
                "raw_text": doc.raw_text,
            }
            for doc in documents
        ]

        logger.info(
            f"[Document Understanding Agent] Starting concurrent extraction for {len(docs_payload)} documents in bundle {bundle_id}"
        )

        # ── Phase 1: Concurrent Parsing in ThreadPoolExecutor ──────────────────
        max_workers = min(len(docs_payload), 4) or 1
        parsed_outputs_by_id = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_doc = {
                executor.submit(_parse_single_doc_worker, payload): payload["document_id"]
                for payload in docs_payload
            }
            for future in as_completed(future_to_doc):
                doc_id = future_to_doc[future]
                try:
                    parsed_outputs_by_id[doc_id] = future.result()
                except Exception as exc:
                    logger.error(f"[Document Understanding Agent] Worker thread crashed for {doc_id}: {exc}")
                    parsed_outputs_by_id[doc_id] = {
                        "document_id": doc_id,
                        "doc_type": "unknown",
                        "raw_text": None,
                        "result": None,
                        "error": str(exc),
                    }

        # ── Phase 2: Deterministic Canonical Order Persistence in Main Thread ──
        # Guarantee purchase_order is saved first so subsequent invoice/grn po_id matches resolve
        def _get_sort_key(doc_obj):
            try:
                return CANONICAL_DOC_ORDER.index(doc_obj.doc_type)
            except ValueError:
                return 99

        sorted_documents = sorted(documents, key=_get_sort_key)

        for doc in sorted_documents:
            output = parsed_outputs_by_id.get(doc.document_id)
            if not output:
                continue

            raw_text = output.get("raw_text")
            if raw_text and not doc.raw_text:
                doc.raw_text = raw_text

            result = output.get("result")

            if result and result.success and result.extracted_obj:
                success, data = extraction_service.persist_extraction_result(db, doc, result)
                if success:
                    extracted_results[doc.doc_type] = data
            else:
                if result:
                    extraction_service.persist_extraction_result(db, doc, result)
                else:
                    doc.extraction_status = "failed"
                    db.commit()

        # Update bundle status in DB to 'extracted'
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        if bundle:
            bundle.status = "extracted"
            db.commit()

        total_elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[Document Understanding Agent] Bundle {bundle_id} concurrent extraction completed in {total_elapsed_ms}ms."
        )

    except Exception as e:
        logger.error(f"Error in Document Understanding Agent: {e}", exc_info=True)
    finally:
        db.close()

    return {
        **state,
        "extracted": extracted_results,
    }
