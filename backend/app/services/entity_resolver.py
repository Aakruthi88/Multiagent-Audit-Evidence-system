"""
Entity Resolver Service - app/services/entity_resolver.py
---------------------------------------------------------
DB-driven resolution of domain entities and audit bundle association.

Priority Order:
1. transaction_reference (e.g. TXN-2026-180, TXN 2026 180, TXN-2026-001)
2. bundle_uuid (valid UUID)
3. invoice_number (INV-200005, INV 200005, invoice 200005, 200005)
4. po_number (PO-100005, PO 100005, PO#100005, 100005)
5. grn_number (GRN-2026-0005, GRN 2026 0005, GRN#2026-0005)
6. delivery_note (DN-1001, delivery note 1001)
7. bank_reference (Ref6821782, REF-6821782)
8. bank_account (account numbers)
9. vendor_name (normalized substring / token match)

LLM identifies WHAT entity strings exist in query; DB decides WHICH bundle(s) they belong to.
"""

import re
import uuid as _uuid_lib
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.logging import logger
from app.db.session import SessionLocal
from app.models.models import (
    AuditBundle, Invoice, InvoiceLineItem, PurchaseOrder, POLineItem,
    GRN, GRNLineItem, BankStatement, BankTransaction, Vendor
)


def is_valid_uuid(val: Any) -> bool:
    if not val or not isinstance(val, str):
        return False
    try:
        _uuid_lib.UUID(str(val).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def normalize_code(raw: str) -> str:
    """Normalize formatted identifiers by stripping spaces, hyphens, hashes, and lowercasing."""
    if not raw:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', raw).lower()


def extract_potential_entities(query: str) -> List[Dict[str, str]]:
    """
    Extract candidate entity tokens/patterns from user text.
    Returns list of dicts: [{"raw": ..., "normalized": ..., "type_hint": ...}]
    """
    if not query:
        return []
    
    candidates = []

    # 1. UUID check
    uuid_matches = re.findall(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', query)
    for u in uuid_matches:
        candidates.append({"raw": u, "normalized": u.lower(), "type_hint": "bundle_uuid"})

    # 2. Transaction reference (e.g. TXN-2026-180, TXN 2026 180, TXN2026180, TXN-2025-0001)
    txn_matches = re.findall(r'\b(?:TXN|txn)[-_\s]?(?:\d{4}[-_\s]?)?\d{1,5}\b', query, re.I)
    for t in txn_matches:
        candidates.append({"raw": t, "normalized": normalize_code(t), "type_hint": "transaction_reference"})

    # 3. GRN numbers (e.g. GRN-2026-0005, GRN 2026 0005, GRN#2026-0005, GRN20260005, GRN-1001)
    grn_matches = re.findall(r'\b(?:GRN|grn)[#\s_-]?(?:\d{4}[-_\s]?)?\d{1,5}\b', query, re.I)
    for g in grn_matches:
        candidates.append({"raw": g, "normalized": normalize_code(g), "type_hint": "grn_number"})

    # 4. Delivery note numbers (e.g. DN-100005, DN 100005, Delivery Note #: DN-100005, Delivery Note 100005, Challan No: DN-999)
    # Must NOT match "GOODS NOTE", "DEMO NOTE", or "D" inside "GOODS"
    dn_matches = re.findall(r'\b(?:DN|delivery\s+note|delivery\s+challan|challan)\s*(?:[#:\-]|no\.?)?\s*([A-Za-z0-9][A-Za-z0-9\-_]*)\b', query, re.I)
    for dn in dn_matches:
        if dn.lower() not in ("date", "note", "goods", "number", "no", "total"):
            candidates.append({"raw": dn, "normalized": normalize_code(dn), "type_hint": "delivery_note"})

    # 5. Invoice numbers (e.g. INV-200005, INV 200005, invoice #200005, invoice 200005, 200005)
    inv_matches = re.findall(r'\b(?:INV|invoice|tax\s+invoice)[#\s_-]?[a-zA-Z0-9\-_/]{3,20}\b', query, re.I)
    for i in inv_matches:
        candidates.append({"raw": i, "normalized": normalize_code(i), "type_hint": "invoice_number"})

    # 6. PO numbers (e.g. PO-100005, PO 100005, PO#100005, po 100005)
    # Exclude PO Box, PO Date
    po_matches = re.findall(r'\b(?:PO|po|purchase\s+order)\s*(?:[#:\-]|no\.?)?\s*(?!(?:box|date|terms|total|amount|line)\b)([a-zA-Z0-9\-_]{3,20})\b', query, re.I)
    for p in po_matches:
        candidates.append({"raw": p, "normalized": normalize_code(p), "type_hint": "po_number"})

    # 7. Bank reference (e.g. Ref6821782, REF-6821782, Ref 6821782, reference 6821782)
    bank_ref_matches = re.findall(r'\b(?:REF|ref|reference)[#\s_-]?[a-zA-Z0-9]{4,20}\b', query, re.I)
    for r in bank_ref_matches:
        candidates.append({"raw": r, "normalized": normalize_code(r), "type_hint": "bank_reference"})

    # 8. Standalone digits (5-7 digits) if not already matched
    digit_matches = re.findall(r'\b\d{5,7}\b', query)
    for d in digit_matches:
        candidates.append({"raw": d, "normalized": d, "type_hint": "generic_id"})

    return candidates


def resolve_entities_from_db(db: Session, query: str) -> Dict[str, Any]:
    """
    Resolve all matching entities from user query against SQLite database using priority order.
    Returns:
    {
       "resolved": True/False,
       "bundle_id": str or None,
       "matches": [
          {"entity_type": ..., "entity_value": ..., "bundle_id": ...}
       ],
       "error": None or {"error_type": "ENTITY_NOT_FOUND", "entity_type": ..., "entity_value": ...}
    }
    """
    if not query or not query.strip():
        return {
            "resolved": False,
            "bundle_id": None,
            "matches": [],
            "error": {"error_type": "ENTITY_NOT_FOUND", "entity_type": "empty_query", "entity_value": ""}
        }

    q_text = query.strip()
    q_norm = normalize_code(q_text)
    q_lower = q_text.lower()

    matches = []
    bundle_ids_found = set()

    # ── Strategy 1: Transaction Reference ──────────────────────────────────────
    bundles = db.query(AuditBundle).all()
    for b in bundles:
        if b.txn_reference:
            b_txn_norm = normalize_code(b.txn_reference)
            if b_txn_norm and (b_txn_norm in q_norm or b.txn_reference.lower() in q_lower):
                b_id = str(b.bundle_id)
                matches.append({
                    "entity_type": "transaction_reference",
                    "entity_value": b.txn_reference,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 2: Bundle UUID ────────────────────────────────────────────────
    for b in bundles:
        b_id_str = str(b.bundle_id).lower()
        if b_id_str in q_lower:
            matches.append({
                "entity_type": "bundle_uuid",
                "entity_value": b_id_str,
                "bundle_id": b_id_str
            })
            bundle_ids_found.add(b_id_str)

    # ── Strategy 3: Invoice Number ─────────────────────────────────────────────
    invoices = db.query(Invoice).all()
    for inv in invoices:
        if inv.invoice_number:
            inv_norm = normalize_code(inv.invoice_number)
            if (inv_norm and inv_norm in q_norm) or (inv.invoice_number.lower() in q_lower):
                b_id = str(inv.bundle_id)
                matches.append({
                    "entity_type": "invoice_number",
                    "entity_value": inv.invoice_number,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 4: PO Number ──────────────────────────────────────────────────
    pos = db.query(PurchaseOrder).all()
    for po in pos:
        if po.po_number:
            po_norm = normalize_code(po.po_number)
            if (po_norm and po_norm in q_norm) or (po.po_number.lower() in q_lower):
                b_id = str(po.bundle_id)
                matches.append({
                    "entity_type": "po_number",
                    "entity_value": po.po_number,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 5: GRN Number ─────────────────────────────────────────────────
    grns = db.query(GRN).all()
    for grn in grns:
        if grn.grn_number:
            grn_norm = normalize_code(grn.grn_number)
            if (grn_norm and grn_norm in q_norm) or (grn.grn_number.lower() in q_lower):
                b_id = str(grn.bundle_id)
                matches.append({
                    "entity_type": "grn_number",
                    "entity_value": grn.grn_number,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 6: Delivery Note Number ──────────────────────────────────────
    for grn in grns:
        if grn.delivery_note_number:
            dn_norm = normalize_code(grn.delivery_note_number)
            if (dn_norm and dn_norm in q_norm) or (grn.delivery_note_number.lower() in q_lower):
                b_id = str(grn.bundle_id)
                matches.append({
                    "entity_type": "delivery_note",
                    "entity_value": grn.delivery_note_number,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 7: Bank Reference ────────────────────────────────────────────
    bts = db.query(BankTransaction).all()
    for bt in bts:
        ref = bt.extracted_ref
        if ref:
            ref_norm = normalize_code(ref)
            if (ref_norm and ref_norm in q_norm) or (ref.lower() in q_lower):
                stmt = db.query(BankStatement).filter(BankStatement.statement_id == bt.statement_id).first()
                if stmt and stmt.bundle_id:
                    b_id = str(stmt.bundle_id)
                    matches.append({
                        "entity_type": "bank_reference",
                        "entity_value": ref,
                        "bundle_id": b_id
                    })
                    bundle_ids_found.add(b_id)

    # ── Strategy 8: Bank Account Number ───────────────────────────────────────
    stmts = db.query(BankStatement).all()
    for stmt in stmts:
        if stmt.account_number:
            acc_norm = normalize_code(stmt.account_number)
            if (acc_norm and acc_norm in q_norm) or (stmt.account_number.lower() in q_lower):
                b_id = str(stmt.bundle_id)
                matches.append({
                    "entity_type": "bank_account",
                    "entity_value": stmt.account_number,
                    "bundle_id": b_id
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 9: Vendor Name ───────────────────────────────────────────────
    if not bundle_ids_found:
        vendors = db.query(Vendor).all()
        stop_words = {'pvt', 'ltd', 'inc', 'corp', 'co', 'and', 'was', 'made', 'to', 'payment', 'paid', 'invoice', 'po', 'grn', 'for', 'with', 'the', 'is', 'has', 'been', 'what', 'which', 'show', 'compare', 'does'}
        q_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', q_lower)
        q_words = set(q_clean.split()) - stop_words

        for v in vendors:
            v_name = (v.name_normalized or getattr(v, 'name_raw', '') or '').lower()
            if not v_name:
                continue
            v_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', v_name)
            v_no_space = normalize_code(v_name)
            core_v = v_no_space.replace('pvtltd', '').replace('ltd', '').replace('pvt', '')

            is_vendor_match = False
            if core_v and len(core_v) >= 4 and core_v in q_norm:
                is_vendor_match = True
            else:
                v_words = set(v_clean.split()) - stop_words
                if v_words and len(q_words & v_words) >= 1:
                    is_vendor_match = True

            if is_vendor_match:
                inv = db.query(Invoice).filter(Invoice.vendor_id == v.vendor_id).first()
                if inv and inv.bundle_id:
                    b_id = str(inv.bundle_id)
                    matches.append({
                        "entity_type": "vendor_name",
                        "entity_value": v.name_normalized or v.name_raw,
                        "bundle_id": b_id
                    })
                    bundle_ids_found.add(b_id)
                else:
                    po = db.query(PurchaseOrder).filter(PurchaseOrder.vendor_id == v.vendor_id).first()
                    if po and po.bundle_id:
                        b_id = str(po.bundle_id)
                        matches.append({
                            "entity_type": "vendor_name",
                            "entity_value": v.name_normalized or v.name_raw,
                            "bundle_id": b_id
                        })
                        bundle_ids_found.add(b_id)

    # ── Strategy 10: General Bank / Statement queries without specific ID ──────
    if not bundle_ids_found and any(k in q_lower for k in ["closing balance", "opening balance", "bank balance", "statement balance", "bank statement"]):
        stmt = db.query(BankStatement).first()
        if stmt and stmt.bundle_id:
            b_id = str(stmt.bundle_id)
            matches.append({
                "entity_type": "bank_account",
                "entity_value": stmt.account_number or "default_statement",
                "bundle_id": b_id
            })
            bundle_ids_found.add(b_id)

    # ── Strategy 11: Semantic Vector Search (ChromaDB) ──────────────────────────
    if not bundle_ids_found:
        sem_matches = semantic_search_documents(db, q_text, top_k=5)
        for sm in sem_matches:
            # Score threshold check to avoid irrelevant document false positives
            if sm.get("score", 0.0) >= 0.20 and sm.get("bundle_id"):
                b_id = sm["bundle_id"]
                matches.append({
                    "entity_type": "semantic_search",
                    "entity_value": sm.get("doc_number") or sm.get("doc_type") or "semantic_match",
                    "bundle_id": b_id,
                    "doc_type": sm.get("doc_type"),
                    "score": sm.get("score"),
                })
                bundle_ids_found.add(b_id)

    # ── Strategy 12: General Audit / Discrepancy queries without exact ID ──────
    if not bundle_ids_found and any(k in q_lower for k in ["discrepanc", "anomaly", "anomalies", "mismatch", "audit", "evidence", "supports this transaction"]):
        latest_bundle = db.query(AuditBundle).order_by(AuditBundle.created_at.desc()).first()
        if latest_bundle:
            b_id = str(latest_bundle.bundle_id)
            matches.append({
                "entity_type": "general_audit",
                "entity_value": latest_bundle.txn_reference or "latest_bundle",
                "bundle_id": b_id
            })
            bundle_ids_found.add(b_id)

    # De-duplicate matches
    unique_matches = []
    seen = set()
    for m in matches:
        key = (m["entity_type"], m["entity_value"], m["bundle_id"])
        if key not in seen:
            seen.add(key)
            unique_matches.append(m)

    if not unique_matches or not bundle_ids_found:
        extracted_cands = extract_potential_entities(query)
        err_type = extracted_cands[0]["type_hint"] if extracted_cands else "unknown"
        err_val = extracted_cands[0]["raw"] if extracted_cands else query
        return {
            "resolved": False,
            "bundle_id": None,
            "matches": [],
            "error": {
                "error_type": "ENTITY_NOT_FOUND",
                "entity_type": err_type,
                "entity_value": err_val
            }
        }

    primary_bundle_id = list(bundle_ids_found)[0]
    logger.info(f"[EntityResolver] Resolved query '{query}' -> matches={unique_matches}, primary_bundle={primary_bundle_id}")

    return {
        "resolved": True,
        "bundle_id": primary_bundle_id,
        "matches": unique_matches,
        "error": None
    }


def sync_chroma_bundle_index(db: Session):
    """Index all DB bundles, documents, line items, and bank transactions in ChromaDB."""
    try:
        from app.agents.search_agent import _get_chroma
        collection = _get_chroma()
        if not collection:
            return

        bundles = db.query(AuditBundle).all()
        documents = []
        ids = []
        metadatas = []

        for b in bundles:
            b_id = str(b.bundle_id)

            # Invoice
            inv = db.query(Invoice).filter(Invoice.bundle_id == b.bundle_id).first()
            if inv:
                v = db.query(Vendor).filter(Vendor.vendor_id == inv.vendor_id).first() if inv.vendor_id else None
                vname = v.name_normalized if v else ""
                inv_lines = db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id == inv.invoice_id).all()
                line_descs = ", ".join([l.description for l in inv_lines if l.description])
                
                text_content = (
                    f"Invoice {inv.invoice_number} for vendor {vname} ({v.name_raw if v else ''}). "
                    f"Subtotal: {inv.subtotal}, Tax: {inv.tax_amount}, Total amount: {inv.total_amount}. "
                    f"Invoice date: {inv.invoice_date}, Due date: {inv.due_date}. "
                    f"Line items: {line_descs}. Transaction ref: {b.txn_reference}"
                )
                documents.append(text_content)
                ids.append(f"{b_id}_inv_{inv.invoice_id}")
                metadatas.append({
                    "bundle_id": b_id,
                    "doc_type": "invoice",
                    "doc_number": str(inv.invoice_number or ''),
                    "vendor_name": str(vname or ''),
                    "txn_reference": str(b.txn_reference or ''),
                })

            # Purchase Order
            po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == b.bundle_id).first()
            if po:
                po_lines = db.query(POLineItem).filter(POLineItem.po_id == po.po_id).all()
                line_descs = ", ".join([f"{l.description} (item code {l.item_code or ''})" for l in po_lines if l.description])
                text_content = (
                    f"Purchase Order PO {po.po_number}. Total amount: {po.total_amount}, Subtotal: {po.subtotal}. "
                    f"PO date: {po.po_date}. Requisitioner: {po.requisitioner}. Terms: {po.shipping_terms}. "
                    f"Line items: {line_descs}. Transaction ref: {b.txn_reference}"
                )
                documents.append(text_content)
                ids.append(f"{b_id}_po_{po.po_id}")
                metadatas.append({
                    "bundle_id": b_id,
                    "doc_type": "purchase_order",
                    "doc_number": str(po.po_number or ''),
                    "vendor_name": "",
                    "txn_reference": str(b.txn_reference or ''),
                })

            # GRN
            grn = db.query(GRN).filter(GRN.bundle_id == b.bundle_id).first()
            if grn:
                grn_lines = db.query(GRNLineItem).filter(GRNLineItem.grn_id == grn.grn_id).all()
                line_descs = ", ".join([f"{l.description} received {l.qty_received}" for l in grn_lines if l.description])
                text_content = (
                    f"Goods Received Note GRN {grn.grn_number} delivery note {grn.delivery_note_number}. "
                    f"GRN date: {grn.grn_date}. Received condition: {grn.received_condition}. "
                    f"Line items received: {line_descs}. Transaction ref: {b.txn_reference}"
                )
                documents.append(text_content)
                ids.append(f"{b_id}_grn_{grn.grn_id}")
                metadatas.append({
                    "bundle_id": b_id,
                    "doc_type": "grn",
                    "doc_number": str(grn.grn_number or ''),
                    "vendor_name": "",
                    "txn_reference": str(b.txn_reference or ''),
                })

            # Bank Statement
            stmt = db.query(BankStatement).filter(BankStatement.bundle_id == b.bundle_id).first()
            if stmt:
                bts = db.query(BankTransaction).filter(BankTransaction.statement_id == stmt.statement_id).all()
                txn_descs = ", ".join([f"{t.txn_date} {t.description_raw} (debit: {t.debit_amount}, credit: {t.credit_amount}, ref: {t.extracted_ref or ''})" for t in bts])
                text_content = (
                    f"Bank Statement account {stmt.account_number} period {stmt.period_start} to {stmt.period_end}. "
                    f"Opening balance: {stmt.opening_balance}, Closing balance: {stmt.closing_balance}. "
                    f"Bank transactions: {txn_descs}. Transaction ref: {b.txn_reference}"
                )
                documents.append(text_content)
                ids.append(f"{b_id}_bank_{stmt.statement_id}")
                metadatas.append({
                    "bundle_id": b_id,
                    "doc_type": "bank_statement",
                    "doc_number": str(stmt.account_number or ''),
                    "vendor_name": "",
                    "txn_reference": str(b.txn_reference or ''),
                })

        if documents:
            collection.upsert(documents=documents, ids=ids, metadatas=metadatas)
            logger.info(f"[EntityResolver] Synced {len(documents)} document chunks into ChromaDB collection")
    except Exception as exc:
        logger.warning(f"[EntityResolver] ChromaDB indexing error: {exc}")


def semantic_search_documents(db: Session, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Perform vector similarity search over all indexed audit documents."""
    sync_chroma_bundle_index(db)
    try:
        from app.agents.search_agent import _get_chroma
        collection = _get_chroma()
        if not collection:
            return []

        res = collection.query(query_texts=[query], n_results=top_k)
        results = []
        if res and res.get("documents") and res.get("documents")[0]:
            docs = res["documents"][0]
            metadatas = res["metadatas"][0] if res.get("metadatas") else [{}] * len(docs)
            distances = res["distances"][0] if res.get("distances") else [0.0] * len(docs)

            for doc, meta, dist in zip(docs, metadatas, distances):
                results.append({
                    "bundle_id": meta.get("bundle_id"),
                    "doc_type": meta.get("doc_type"),
                    "doc_number": meta.get("doc_number"),
                    "vendor_name": meta.get("vendor_name"),
                    "txn_reference": meta.get("txn_reference"),
                    "snippet": doc[:200],
                    "distance": float(dist),
                    "score": round(max(0.0, 1.0 - float(dist)), 3)
                })
        return results
    except Exception as exc:
        logger.warning(f"[EntityResolver] Semantic search error: {exc}")
        return []

