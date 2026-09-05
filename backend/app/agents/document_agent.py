from app.agents.state import BundleState
from app.db.session import SessionLocal
from app.models.models import Document, AuditBundle
from app.services.pdf_service import pdf_service
from app.services.extraction_service import extraction_service
from app.core.logging import logger

def document_understanding_node(state: BundleState) -> BundleState:
    """
    Document Understanding Agent node:
    - Extracts raw text for each document in the bundle
    - Executes structured extraction (LLM / Pydantic schema)
    - Saves structured records in PostgreSQL DB
    """
    bundle_id = state.get("bundle_id")
    db = SessionLocal()
    extracted_results = state.get("extracted", {})

    try:
        documents = db.query(Document).filter(Document.bundle_id == bundle_id).all()
        
        for doc in documents:
            logger.info(f"[Document Understanding Agent] Processing {doc.doc_type} for bundle {bundle_id}")
            
            # Step 1: Extract PDF text if raw_text is missing
            if not doc.raw_text:
                try:
                    doc.raw_text = pdf_service.extract_text(doc.file_path)
                    db.commit()
                except Exception as e:
                    logger.error(f"Failed PDF text extraction for {doc.document_id}: {e}")
                    doc.extraction_status = "failed"
                    db.commit()
                    continue

            # Step 2: Run LLM/Pydantic structured extraction & DB persistence
            success, data = extraction_service.extract_document(db, doc)
            if success:
                extracted_results[doc.doc_type] = data

        # Update bundle status in DB to 'extracted'
        bundle = db.query(AuditBundle).filter(AuditBundle.bundle_id == bundle_id).first()
        if bundle:
            bundle.status = "extracted"
            db.commit()

        logger.info(f"[Document Understanding Agent] Bundle {bundle_id} extraction completed.")

    except Exception as e:
        logger.error(f"Error in Document Understanding Agent: {e}")
    finally:
        db.close()

    return {
        **state,
        "extracted": extracted_results
    }
